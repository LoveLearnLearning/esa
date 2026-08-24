import 'dart:convert';
import 'dart:typed_data';

DateTime _dateValue(dynamic value, DateTime fallback) =>
    DateTime.tryParse(value?.toString() ?? '') ?? fallback;

/// 华中科技大学统一身份认证验证码挑战。
class HustImportChallenge {
  const HustImportChallenge({
    required this.challengeId,
    required this.captchaImageBase64,
    required this.captchaMimeType,
    required this.expiresAt,
    required this.recommendedSemesterName,
    required this.recommendedStartDate,
    required this.recommendedEndDate,
  });

  final String challengeId;
  final String captchaImageBase64;
  final String captchaMimeType;
  final DateTime expiresAt;
  final String recommendedSemesterName;
  final DateTime recommendedStartDate;
  final DateTime recommendedEndDate;

  Uint8List get captchaBytes {
    final separator = captchaImageBase64.indexOf(',');
    final payload = separator >= 0
        ? captchaImageBase64.substring(separator + 1)
        : captchaImageBase64;
    try {
      return base64Decode(payload);
    } on FormatException {
      return Uint8List(0);
    }
  }

  factory HustImportChallenge.fromJson(Map<String, dynamic> json) {
    final now = DateTime.now();
    return HustImportChallenge(
      challengeId: json['challenge_id']?.toString() ?? '',
      captchaImageBase64: json['captcha_image_base64']?.toString() ?? '',
      captchaMimeType: json['captcha_mime_type']?.toString() ?? 'image/jpeg',
      expiresAt: _dateValue(
        json['expires_at'],
        now.add(const Duration(minutes: 5)),
      ),
      recommendedSemesterName:
          json['recommended_semester_name']?.toString() ?? '',
      recommendedStartDate: _dateValue(json['recommended_start_date'], now),
      recommendedEndDate: _dateValue(
        json['recommended_end_date'],
        now.add(const Duration(days: 18 * 7 - 1)),
      ),
    );
  }
}
