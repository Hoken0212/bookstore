import os
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify
from app.models.book import Book
from app import supabase
from google import genai

api_bp = Blueprint('api', __name__)

GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
AI_CACHE_TTL_SECONDS = int(os.getenv('AI_CACHE_TTL_SECONDS', '600'))
AI_REQUEST_TIMEOUT_SECONDS = int(os.getenv('AI_REQUEST_TIMEOUT_SECONDS', '25'))
_gemini_client = None
_ai_cache = {}
_ai_executor = ThreadPoolExecutor(max_workers=int(os.getenv('AI_MAX_WORKERS', '4')))


def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('GEMINI_API_KEY chưa được cấu hình trong file .env')
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def get_cached_response(cache_key):
    cached = _ai_cache.get(cache_key)
    if not cached:
        return None
    created_at, value = cached
    if time.time() - created_at > AI_CACHE_TTL_SECONDS:
        _ai_cache.pop(cache_key, None)
        return None
    return value


def set_cached_response(cache_key, value):
    _ai_cache[cache_key] = (time.time(), value)
    if len(_ai_cache) > 100:
        oldest_key = min(_ai_cache, key=lambda key: _ai_cache[key][0])
        _ai_cache.pop(oldest_key, None)


def generate_ai_text(prompt_text, cache_key):
    cached = get_cached_response(cache_key)
    if cached:
        return cached

    future = _ai_executor.submit(
        get_gemini_client().models.generate_content,
        model=GEMINI_MODEL,
        contents=prompt_text
    )
    response = future.result(timeout=AI_REQUEST_TIMEOUT_SECONDS)
    text = (response.text or '').strip()
    set_cached_response(cache_key, text)
    return text

@api_bp.route('/ai/recommend', methods=['POST'])
def ai_recommend():
    data = request.json or {}
    user_input = data.get('message', '').strip()

    if not user_input:
        return jsonify({'error': 'Vui lòng nhập yêu cầu'}), 400

    books = Book.get_all(per_page=50)
    books_context = [
        f"- {b.title} ({b.author}) - {b.category_name} - {b.price:,.0f}đ"
        for b in books[:30]
    ]

    system_prompt = f"""Bạn là trợ lý tư vấn sách thông minh và cực kỳ có gu thẩm mỹ cho nhà sách BookStore. 
    Hãy giúp khách hàng tìm kiếm và gợi ý sách phù hợp với nhu cầu của họ.
    
    YÊU CẦU BẮT BUỘC VỀ TRÌNH BÀY:
    - Phải trình bày văn bản cực kỳ đẹp mắt, gọn gàng và sang trọng.
    - Bắt buộc phải XUỐNG DÒNG rõ ràng giữa các ý.
    - Sử dụng gạch đầu dòng khi liệt kê tên sách để khách dễ đọc.
    - Trả lời bằng tiếng Việt, thân thiện và hữu ích.
    - Chỉ gợi ý những sách có trong danh sách được cung cấp dưới đây.
    
    Danh sách sách hiện có:
    {"\n".join(books_context)}"""

    prompt_text = f"{system_prompt}\n\nKhách hàng hỏi: {user_input}"

    try:
        cache_key = ('recommend', user_input.lower(), tuple(books_context))
        return jsonify({'response': generate_ai_text(prompt_text, cache_key)})
    except Exception as e:
        print(f"Lỗi Gemini Recommend: {e}")
        return jsonify({'error': 'Hệ thống AI đang bận hoặc chưa cấu hình đúng. Vui lòng thử lại sau.'}), 503


@api_bp.route('/ai/summarize/<int:book_id>', methods=['GET'])
def ai_summarize(book_id):
    book = Book.get_by_id(book_id)
    if not book or not book.description:
        return jsonify({'error': 'Không có mô tả sách'}), 404

    prompt_text = f"Bạn là trợ lý tóm tắt sách chuyên nghiệp. Yêu cầu văn phong cuốn hút, trình bày đẹp mắt, có xuống dòng ngắt ý rõ ràng.\n\nHãy tóm tắt ngắn gọn (3-4 câu) nội dung cuốn sách này bằng tiếng Việt:\n\n{book.description}"

    try:
        cache_key = ('summary', book_id, book.description)
        return jsonify({'summary': generate_ai_text(prompt_text, cache_key)})
    except Exception as e:
        print(f"Lỗi Gemini Summarize: {e}")
        return jsonify({'error': 'Không thể tóm tắt lúc này'}), 503


@api_bp.route('/ai/review-sentiment/<int:book_id>', methods=['GET'])
def ai_review_sentiment(book_id):
    try:
        reviews_result = supabase.table('reviews').select('rating, comment').eq('book_id', book_id).execute()
        reviews = reviews_result.data or []
        if not reviews:
            return jsonify({'analysis': 'Chưa có đánh giá nào cho cuốn sách này.'})

        reviews_text = "\n".join([
            f"- Rating: {r['rating']}/5 - {r.get('comment', '')}"
            for r in reviews[:20]
        ])

        prompt_text = f"Bạn là chuyên gia phân tích dữ liệu. Phân tích điểm mạnh, điểm yếu theo ý kiến độc giả. Yêu cầu trình bày tiếng Việt, cực kỳ ngắn gọn súc tích, chia đoạn và dùng gạch đầu dòng cho thật đẹp mắt.\n\nPhân tích tổng quan các đánh giá sau:\n\n{reviews_text}"

        cache_key = ('sentiment', book_id, reviews_text)
        return jsonify({'analysis': generate_ai_text(prompt_text, cache_key)})
    except Exception as e:
        print(f"Lỗi Gemini Sentiment: {e}")
        return jsonify({'error': 'Không thể phân tích lúc này'}), 503


@api_bp.route('/cart/count', methods=['GET'])
def cart_count():
    from flask import session
    cart = session.get('cart', {})
    return jsonify({'count': sum(cart.values())})


@api_bp.route('/search/suggestions', methods=['GET'])
def search_suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    try:
        result = supabase.table('books').select('id, title, author').or_(
            f'title.ilike.%{q}%,author.ilike.%{q}%'
        ).eq('is_active', True).limit(6).execute()
        suggestions = [
            {'id': b['id'], 'title': b['title'], 'author': b['author']}
            for b in (result.data or [])
        ]
        return jsonify(suggestions)
    except Exception as e:
        print(f"Lỗi Search: {e}")
        return jsonify([])
