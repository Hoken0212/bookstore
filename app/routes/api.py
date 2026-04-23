import os
import json
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.models.book import Book
from app import supabase
import anthropic

api_bp = Blueprint('api', __name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[])


def _register_limiter(state):
    limiter.init_app(state.app)


api_bp.record(_register_limiter)

# Model mặc định: Claude 3.5 Sonnet (ổn định trên API Anthropic). Có thể ghi đè bằng ANTHROPIC_MODEL trong .env
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')


def _anthropic_client():
    key = (os.getenv('ANTHROPIC_API_KEY') or '').strip()
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def _anthropic_error_response(exc, public_message):
    if current_app:
        current_app.logger.warning('Anthropic API: %s', exc)
    return jsonify({'error': public_message}), 500


def _build_recommend_system_prompt(books_context_lines):
    return """Bạn là trợ lý tư vấn sách tại BookStore (nhà sách trực tuyến tại Việt Nam).

Nhiệm vụ:
- Lắng nghe nhu cầu, sở thích hoặc tình huống của khách (ví dụ: muốn học quản lý thời gian, tìm sách cho trẻ 8 tuổi, thích tiểu thuyết nhẹ nhàng).
- Gợi ý sách phù hợp **chỉ** từ danh sách bên dưới. Không bịa thêm tựa sách không có trong danh sách.
- Trả lời bằng tiếng Việt tự nhiên, như nhân viên tư vấn: ngắn gọn ở đoạn mở đầu, sau đó có thể liệt kê 2–5 gợi ý với lý do ngắn (một câu mỗi cuốn).
- Nếu không có sách phù hợp trong danh sách, hãy nói thật và gợi ý khách thử mô tả thêm (thể loại, độ tuổi, mục tiêu đọc).

Giọng điệu: thân thiện, lịch sự, không rườm rà; tránh câu mở đầu kiểu máy dịch như "Dựa trên yêu cầu của bạn" nếu có thể thay bằng câu đời thường hơn.

Danh sách sách hiện có:
""" + "\n".join(books_context_lines)


@api_bp.route('/ai/recommend', methods=['POST'])
@limiter.limit('30 per minute')
def ai_recommend():
    """AI book recommendation based on user preferences"""
    data = request.json or {}
    user_input = data.get('message', '').strip()

    if not user_input:
        return jsonify({'error': 'Vui lòng nhập yêu cầu'}), 400

    books = Book.get_all(per_page=50)
    books_context = [
        f"- {b.title} ({b.author}) — {b.category_name} — {b.price:,.0f}đ"
        for b in books[:30]
    ]

    system_prompt = _build_recommend_system_prompt(books_context)

    client = _anthropic_client()
    if not client:
        return jsonify(
            {'error': 'Chưa cấu hình ANTHROPIC_API_KEY trong file .env (Console Anthropic).'}
        ), 503

    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return jsonify({'response': message.content[0].text})
    except Exception as e:
        return _anthropic_error_response(
            e,
            'Không thể kết nối AI. Kiểm tra API key, model ANTHROPIC_MODEL và mạng. Vui lòng thử lại.',
        )


@api_bp.route('/ai/summarize/<int:book_id>', methods=['GET'])
@limiter.limit('60 per minute')
def ai_summarize(book_id):
    """AI summarize book description (cached in DB when columns exist)."""
    refresh = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
    book = Book.get_by_id(book_id)
    if not book or not book.description:
        return jsonify({'error': 'Không có mô tả sách'}), 404

    if not refresh and book.ai_summary_cache_fresh():
        return jsonify({'summary': book.ai_summary, 'cached': True})

    client = _anthropic_client()
    if not client:
        return jsonify({'error': 'Chưa cấu hình ANTHROPIC_API_KEY trong .env.'}), 503

    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Hãy tóm tắt nội dung cuốn sách sau bằng tiếng Việt, "
                    "3–4 câu, văn phong tự nhiên, dễ đọc (tránh liệt kê máy móc):\n\n"
                    f"{book.description}"
                )
            }]
        )
        text = message.content[0].text
        Book.save_ai_summary(book_id, text)
        return jsonify({'summary': text, 'cached': False})
    except Exception as e:
        return _anthropic_error_response(e, 'Không thể tóm tắt. Kiểm tra API key và ANTHROPIC_MODEL.')


@api_bp.route('/ai/review-sentiment/<int:book_id>', methods=['GET'])
@limiter.limit('30 per minute')
def ai_review_sentiment(book_id):
    """Analyze sentiment of book reviews"""
    try:
        reviews_result = supabase.table('reviews').select('rating, comment').eq('book_id', book_id).execute()
        reviews = reviews_result.data or []
    except Exception:
        return jsonify({'error': 'Không thể đọc đánh giá.'}), 500

    if not reviews:
        return jsonify({'analysis': 'Chưa có đánh giá nào cho cuốn sách này.'})

    reviews_text = "\n".join([
        f"- Rating: {r['rating']}/5 - {r.get('comment', '')}"
        for r in reviews[:20]
    ])

    client = _anthropic_client()
    if not client:
        return jsonify({'error': 'Chưa cấu hình ANTHROPIC_API_KEY trong .env.'}), 503

    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    "Dựa trên các đánh giá sau, hãy tóm tắt ngắn gọn bằng tiếng Việt: "
                    "điểm mạnh, điểm cần lưu ý theo ý kiến độc giả. Không cần chào hỏi dài.\n\n"
                    f"{reviews_text}"
                )
            }]
        )
        return jsonify({'analysis': message.content[0].text})
    except Exception as e:
        return _anthropic_error_response(e, 'Không thể phân tích. Kiểm tra API key và ANTHROPIC_MODEL.')


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
    except Exception:
        return jsonify([])
