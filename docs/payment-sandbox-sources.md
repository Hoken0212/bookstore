# Nguồn sandbox MoMo & ZaloPay (GitHub / tài liệu)

## MoMo (Vietnam — ví MoMo, không phải MTN Châu Phi)

- **Org chính thức:** [github.com/momo-wallet](https://github.com/momo-wallet) — repo mẫu: [momo-wallet/payment](https://github.com/momo-wallet/payment) (Java, PHP, C#, Ruby, Python, Node…).
- **Không** có file `.env` “dùng chung cho cả internet” như ZaloPay `2554`. `partnerCode` / `accessKey` / `secretKey` gắn với **tài khoản merchant test** của bạn sau khi đăng ký trên [developers.momo.vn](https://developers.momo.vn) / cổng doanh nghiệp.
- **Test:** [Test instructions](https://developers.momo.vn/v3/docs/payment/onboarding/test-instructions/) — ví test, thẻ test, v.v.

## ZaloPay

- **Credential sandbox công khai (app 2554):** [zalopay-samples/test-apps — credentials/app-2554.env](https://github.com/zalopay-samples/test-apps/blob/main/credentials/app-2554.env) (dùng với QR / create order trên môi trường sandbox).
- **Sample app:** [zalopay-samples](https://github.com/zalopay-samples) (Next.js, disbursement, v.v.).
- **SDK:** [zalopay-oss/zalopay-nodejs](https://github.com/zalopay-oss/zalopay-nodejs) — `env: "sandbox"`.

## Lưu ý bảo mật

- Không copy key **lạ** từ repo cá nhân không rõ nguồn; ưu tiên repo **zalopay-samples** / **momo-wallet** và tài liệu chính thức.
- Không commit file `.env` thật lên Git.
