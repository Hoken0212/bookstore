from flask import Blueprint, request, jsonify
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
import os

ai_bp = Blueprint('ai', __name__)

@ai_bp.route('/chat', methods=['POST'])
def chat_with_ai():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({"error": "Vui lòng nhập tin nhắn"}), 400

    try:
        # Lấy chìa khóa bí mật từ file .env bạn đã cài hồi sáng
        client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        
        # Khung lệnh bắt buộc AI phải tư vấn hay và trình bày đẹp mắt
        prompt_text = f"{HUMAN_PROMPT} Bạn là một trợ lý bán sách ảo cực kỳ chuyên nghiệp, duyên dáng và am hiểu văn học tại nhà sách BookStore. Khách hàng vừa nhắn: '{user_message}'. Hãy tư vấn thật nhiệt tình, trình bày văn bản cực kỳ đẹp mắt, có xuống dòng rõ ràng, chia ý mạch lạc để khách dễ đọc.{AI_PROMPT}"

        # Gọi AI Claude trả lời
        response = client.completions.create(
            model="claude-2.1",
            max_tokens_to_sample=800,
            prompt=prompt_text
        )
        
        ai_reply = response.completion
        return jsonify({"reply": ai_reply})

    except Exception as e:
        print(f"Lỗi AI: {e}")
        return jsonify({"error": "Xin lỗi, trợ lý AI đang bận sắp xếp lại kệ sách. Bạn vui lòng thử lại sau vài giây nhé!"}), 500