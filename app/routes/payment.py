import os
import hmac
import hashlib
import json
import uuid
import time
import qrcode
import io
import base64
import requests
from requests.exceptions import RequestException, Timeout
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.models.order import Order

payment_bp = Blueprint('payment', __name__)

MOMO_PARTNER_CODE = os.getenv('MOMO_PARTNER_CODE', 'MOMO')
MOMO_ACCESS_KEY = os.getenv('MOMO_ACCESS_KEY', '')
MOMO_SECRET_KEY = os.getenv('MOMO_SECRET_KEY', '')
MOMO_ENDPOINT = os.getenv('MOMO_ENDPOINT', 'https://test-payment.momo.vn/v2/gateway/api/create')
MOMO_PHONE = os.getenv('MOMO_PHONE', '0123456789')
# partnerName + storeId — dùng cho mọi requestType phổ biến
MOMO_PARTNER_NAME = os.getenv('MOMO_PARTNER_NAME', 'Test')
MOMO_STORE_ID = os.getenv('MOMO_STORE_ID', 'MomoTestStore')
# payWithATM = form thẻ ATM/NAPAS (docs MoMo). captureWallet = ví MoMo / QR chủ đạo.
MOMO_REQUEST_TYPE = os.getenv('MOMO_REQUEST_TYPE', 'payWithATM')

ZALOPAY_APP_ID = os.getenv('ZALOPAY_APP_ID', '2554')
ZALOPAY_KEY1 = os.getenv('ZALOPAY_KEY1', '')
ZALOPAY_KEY2 = os.getenv('ZALOPAY_KEY2', '')
ZALOPAY_ENDPOINT = os.getenv('ZALOPAY_ENDPOINT', 'https://sb-openapi.zalopay.vn/v2/create')


def generate_qr_base64(data):
    """Generate QR code and return as base64 string"""
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def create_momo_payment(order_id, amount, order_code):
    """Create MoMo payment request. Signature giống sample MoMo; requestType quyết định giao diện cổng."""
    # Đọc env mỗi lần gọi (tránh import module khi .env chưa load; đồng bộ với load_dotenv đúng path trong create_app)
    partner_code = (os.getenv('MOMO_PARTNER_CODE') or 'MOMO').strip()
    access_key = (os.getenv('MOMO_ACCESS_KEY') or '').strip()
    secret_key = (os.getenv('MOMO_SECRET_KEY') or '').strip()
    endpoint = (os.getenv('MOMO_ENDPOINT') or 'https://test-payment.momo.vn/v2/gateway/api/create').strip()
    partner_name = (os.getenv('MOMO_PARTNER_NAME') or 'Test').strip()
    store_id = (os.getenv('MOMO_STORE_ID') or 'MomoTestStore').strip()
    request_type = (os.getenv('MOMO_REQUEST_TYPE') or 'payWithATM').strip()

    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    request_id = f"REQ{order_code}"
    redirect_url = f"{app_url}/payment/callback/momo"
    ipn_url = f"{app_url}/payment/ipn/momo"
    # amount trong chữ ký và JSON phải cùng chuỗi số (sample MoMo dùng str)
    amount_str = str(int(amount))
    order_info = f"Thanh toan don hang {order_code}"

    raw_signature = (
        f"accessKey={access_key}"
        f"&amount={amount_str}"
        f"&extraData="
        f"&ipnUrl={ipn_url}"
        f"&orderId={order_code}"
        f"&orderInfo={order_info}"
        f"&partnerCode={partner_code}"
        f"&redirectUrl={redirect_url}"
        f"&requestId={request_id}"
        f"&requestType={request_type}"
    )

    signature = hmac.new(
        secret_key.encode('utf-8'),
        raw_signature.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    payload = {
        "partnerCode": partner_code,
        "partnerName": partner_name,
        "storeId": store_id,
        "requestId": request_id,
        # Tài liệu ATM/Ví dùng Long; chữ ký vẫn dùng amount_str
        "amount": int(amount),
        "orderId": order_code,
        "orderInfo": order_info,
        "redirectUrl": redirect_url,
        "ipnUrl": ipn_url,
        "requestType": request_type,
        "extraData": "",
        "lang": "vi",
        "signature": signature,
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=10)
        try:
            data = response.json()
        except ValueError:
            return {'resultCode': -1, 'message': 'invalid_response', '_gateway': 'parse'}
        # MoMo có thể trả 4xx kèm JSON (sai key, sai chữ ký…); không dùng raise_for_status để không gộp nhầm thành "mất mạng"
        if response.status_code != 200 and isinstance(data, dict):
            data.setdefault('_gateway', 'http')
        return data
    except Timeout:
        return {'resultCode': -1, 'message': 'timeout', '_gateway': 'timeout'}
    except RequestException as e:
        return {'resultCode': -1, 'message': str(e), '_gateway': 'connection'}


def create_zalopay_payment(order_id, amount, order_code):
    """Create ZaloPay payment request"""
    app_url = os.getenv('APP_URL', 'http://localhost:5000')
    app_time = int(round(time.time() * 1000))
    app_trans_id = f"{time.strftime('%y%m%d')}_{order_code}"

    embed_data = json.dumps({"redirecturl": f"{app_url}/payment/callback/zalopay"})
    items = json.dumps([])

    data = f"{ZALOPAY_APP_ID}|{app_trans_id}|{current_user.id if hasattr(current_user, 'id') else 'user'}|{amount}|{app_time}|{embed_data}|{items}"
    mac = hmac.new(ZALOPAY_KEY1.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest()

    params = {
        "app_id": ZALOPAY_APP_ID,
        "app_user": str(current_user.id if hasattr(current_user, 'id') else 'user'),
        "app_time": app_time,
        "amount": int(amount),
        "app_trans_id": app_trans_id,
        "embed_data": embed_data,
        "item": items,
        "description": f"Thanh toán đơn hàng {order_code}",
        "bank_code": "",
        "mac": mac
    }

    try:
        response = requests.post(ZALOPAY_ENDPOINT, data=params, timeout=10)
        try:
            data = response.json()
        except ValueError:
            if response.status_code == 429:
                return {'return_code': -1, 'return_message': 'rate_limited', '_gateway': 'rate_limit'}
            return {'return_code': -1, 'return_message': 'invalid_response', '_gateway': 'parse'}
        if response.status_code != 200 and isinstance(data, dict):
            data.setdefault('_gateway', 'http')
        return data
    except Timeout:
        return {'return_code': -1, 'return_message': 'timeout', '_gateway': 'timeout'}
    except RequestException as e:
        return {'return_code': -1, 'return_message': str(e), '_gateway': 'connection'}


@payment_bp.route('/process/<int:order_id>/<method>')
@login_required
def process(order_id, method):
    order = Order.get_by_id(order_id)
    if not order:
        flash('Không tìm thấy đơn hàng.', 'danger')
        return redirect(url_for('shop.orders'))

    retry_url = url_for('payment.process', order_id=order.id, method=method)

    if method == 'momo':
        result = create_momo_payment(order_id, order.total_amount, order.order_code)
        if result.get('resultCode') == 0 and result.get('payUrl'):
            qr_data = result['payUrl']
            qr_base64 = generate_qr_base64(qr_data)
            return render_template('shop/payment_qr.html',
                                   order=order,
                                   method='momo',
                                   payment_url=result['payUrl'],
                                   qr_base64=qr_base64,
                                   deeplink=result.get('deeplink', ''),
                                   payment_warning=None,
                                   retry_url=retry_url)

        gw = result.get('_gateway')
        if gw == 'timeout':
            warn = 'Cổng MoMo không phản hồi kịp (timeout). Bạn có thể nhấn «Thử lại» hoặc dùng mã QR dự phòng bên dưới.'
        elif gw == 'connection':
            warn = 'Không kết nối được tới MoMo. Kiểm tra mạng, nhấn «Thử lại», hoặc dùng mã QR dự phòng.'
        elif gw == 'parse':
            warn = 'Phản hồi từ MoMo không hợp lệ. Thử lại sau hoặc dùng mã QR dự phòng.'
        else:
            warn = result.get('message') or 'Không tạo được link thanh toán MoMo. Bạn có thể thử lại hoặc quét mã QR dự phòng.'

        momo_phone = os.getenv('MOMO_PHONE', '0123456789')
        momo_qr_content = f"2|99|{momo_phone}|BookStore|{order.order_code}|0"
        qr_base64 = generate_qr_base64(momo_qr_content)
        return render_template('shop/payment_qr.html',
                               order=order,
                               method='momo',
                               payment_url='',
                               qr_base64=qr_base64,
                               phone=momo_phone,
                               payment_warning=warn,
                               retry_url=retry_url)

    elif method == 'zalopay':
        result = create_zalopay_payment(order_id, order.total_amount, order.order_code)
        if result.get('return_code') == 1 and result.get('order_url'):
            qr_base64 = generate_qr_base64(result['order_url'])
            return render_template('shop/payment_qr.html',
                                   order=order,
                                   method='zalopay',
                                   payment_url=result['order_url'],
                                   qr_base64=qr_base64,
                                   payment_warning=None,
                                   retry_url=retry_url)

        gw = result.get('_gateway')
        if gw == 'timeout':
            warn = 'Cổng ZaloPay không phản hồi kịp (timeout). Nhấn «Thử lại» hoặc dùng mã QR dự phòng.'
        elif gw == 'rate_limit':
            warn = 'ZaloPay sandbox đang giới hạn tần suất gọi (429 Too Many Requests). Đợi một lúc rồi thử lại.'
        elif gw == 'connection':
            warn = 'Không kết nối được tới ZaloPay. Kiểm tra mạng hoặc thử lại.'
        elif gw == 'parse':
            warn = 'Phản hồi từ ZaloPay không hợp lệ. Thử lại sau.'
        else:
            warn = result.get('return_message') or 'Không tạo được link thanh toán ZaloPay. Thử lại hoặc dùng mã QR dự phòng.'

        qr_base64 = generate_qr_base64(f"ZALOPAY|{ZALOPAY_APP_ID}|{order.order_code}|{int(order.total_amount)}")
        return render_template('shop/payment_qr.html',
                               order=order,
                               method='zalopay',
                               payment_url='',
                               qr_base64=qr_base64,
                               payment_warning=warn,
                               retry_url=retry_url)

    flash('Phương thức thanh toán không hợp lệ.', 'danger')
    return redirect(url_for('shop.order_detail', order_id=order_id))


@payment_bp.route('/callback/momo')
def momo_callback():
    result_code = request.args.get('resultCode', '')
    order_id_str = request.args.get('orderId', '')
    if result_code == '0':
        try:
            order_result = __import__('app', fromlist=['supabase']).supabase.table('orders').select('id').eq('order_code', order_id_str).single().execute()
            if order_result.data:
                order = Order.get_by_id(order_result.data['id'])
                if order:
                    order.update_status('paid')
                    flash('Thanh toán MoMo thành công!', 'success')
                    return redirect(url_for('shop.order_detail', order_id=order.id))
        except Exception:
            pass
    flash('Thanh toán thất bại hoặc đã bị hủy.', 'danger')
    return redirect(url_for('shop.orders'))


@payment_bp.route('/callback/zalopay')
def zalopay_callback():
    status = request.args.get('status', '')
    app_trans_id = request.args.get('apptransid', '') or request.args.get('app_trans_id', '')
    if status == '1' and app_trans_id:
        # app_trans_id format: yyMMdd_<order_code> (same as create_zalopay_payment)
        if '_' in app_trans_id:
            order_code = app_trans_id.split('_', 1)[1]
            try:
                from app import supabase as sb
                r = sb.table('orders').select('id').eq('order_code', order_code).limit(1).execute()
                rows = r.data or []
                if rows and rows[0].get('id'):
                    order = Order.get_by_id(rows[0]['id'])
                    if order:
                        order.update_status('paid')
                        flash('Thanh toán ZaloPay thành công!', 'success')
                        return redirect(url_for('shop.order_detail', order_id=order.id))
            except Exception:
                pass
        flash('Thanh toán ZaloPay thành công!', 'success')
    else:
        flash('Thanh toán ZaloPay thất bại.', 'danger')
    return redirect(url_for('shop.orders'))


@payment_bp.route('/ipn/momo', methods=['POST'])
def momo_ipn():
    """MoMo IPN handler"""
    data = request.json or {}
    result_code = data.get('resultCode', -1)
    order_id = data.get('orderId', '')
    if result_code == 0:
        try:
            from app import supabase
            order_result = supabase.table('orders').update({'status': 'paid', 'payment_status': 'paid'}).eq('order_code', order_id).execute()
        except Exception:
            pass
    return jsonify({'status': 0})
