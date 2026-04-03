import os
import json
from flask import Blueprint, request, jsonify
from flask_login import current_user
from app.models.book import Book
from app import supabase
import anthropic

api_bp = Blueprint('api', __name__)
ai_client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY', ''))


@api_bp.route('/ai/recommend', methods=['POST'])
def ai_recommend():
    """AI book recommendation based on user preferences"""
    data = request.json or {}
    user_input = data.get('message', '').strip()

    if not user_input:
        return jsonify({'error': 'Vui lòng nhập yêu cầu'}), 400

    # Get available books for context
    books = Book.get_all(per_page=50)
    books_context = [
        f"- {b.title} ({b.author}) - {b.category_name} - {b.price:,.0f}đ"
        for b in books[:30]
    ]

    system_prompt = """Bạn là trợ lý tư vấn sách thông minh cho nhà sách BookStore. 
    Hãy giúp khách hàng tìm kiếm và gợi ý sách phù hợp với nhu cầu của họ.
    Trả lời bằng tiếng Việt, thân thiện và hữu ích.
    Chỉ gợi ý những sách có trong danh sách được cung cấp.
    
    Danh sách sách hiện có:
    """ + "\n".join(books_context)

    try:
        message = ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        return jsonify({'response': message.content[0].text})
    except Exception as e:
        return jsonify({'error': 'Không thể kết nối AI. Vui lòng thử lại.'}), 500


@api_bp.route('/ai/summarize/<int:book_id>', methods=['GET'])
def ai_summarize(book_id):
    """AI summarize book description"""
    book = Book.get_by_id(book_id)
    if not book or not book.description:
        return jsonify({'error': 'Không có mô tả sách'}), 404

    try:
        message = ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"Tóm tắt ngắn gọn (3-4 câu) nội dung cuốn sách này bằng tiếng Việt:\n\n{book.description}"
            }]
        )
        return jsonify({'summary': message.content[0].text})
    except Exception as e:
        return jsonify({'error': 'Không thể tóm tắt'}), 500


@api_bp.route('/ai/review-sentiment/<int:book_id>', methods=['GET'])
def ai_review_sentiment(book_id):
    """Analyze sentiment of book reviews"""
    try:
        reviews_result = supabase.table('reviews').select('rating, comment').eq('book_id', book_id).execute()
        reviews = reviews_result.data or []
        if not reviews:
            return jsonify({'analysis': 'Chưa có đánh giá nào cho cuốn sách này.'})

        reviews_text = "\n".join([
            f"- Rating: {r['rating']}/5 - {r.get('comment', '')}"
            for r in reviews[:20]
        ])

        message = ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": f"Phân tích tổng quan các đánh giá sau cho cuốn sách và cho biết điểm mạnh, điểm yếu theo ý kiến độc giả (trả lời tiếng Việt, ngắn gọn):\n\n{reviews_text}"
            }]
        )
        return jsonify({'analysis': message.content[0].text})
    except Exception as e:
        return jsonify({'error': 'Không thể phân tích'}), 500


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
