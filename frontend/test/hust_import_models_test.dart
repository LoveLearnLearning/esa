import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/hust_import_models.dart';

void main() {
  test('HUST challenge decodes captcha and recommendations', () {
    final challenge = HustImportChallenge.fromJson({
      'challenge_id': 'challenge-1',
      'captcha_image_base64': base64Encode([1, 2, 3]),
      'captcha_mime_type': 'image/jpeg',
      'expires_at': '2026-08-12T10:00:00+08:00',
      'recommended_semester_name': '2026-2027 秋季学期',
      'recommended_start_date': '2026-08-31',
      'recommended_end_date': '2027-01-17',
    });

    expect(challenge.challengeId, 'challenge-1');
    expect(challenge.captchaBytes, [1, 2, 3]);
    expect(challenge.recommendedStartDate, DateTime(2026, 8, 31));
    expect(challenge.recommendedEndDate, DateTime(2027, 1, 17));
  });

  test('HUST challenge accepts a data URL captcha', () {
    final challenge = HustImportChallenge.fromJson({
      'captcha_image_base64': 'data:image/png;base64,${base64Encode([4, 5])}',
    });

    expect(challenge.captchaBytes, [4, 5]);
  });

  test('credentials are allowed only over HTTPS or to local development', () {
    expect(
      ApiClient(baseUrl: 'https://api.example.com')
          .allowsCredentialSubmission,
      isTrue,
    );
    expect(
      ApiClient(baseUrl: 'http://127.0.0.1:8000')
          .allowsCredentialSubmission,
      isTrue,
    );
    expect(
      ApiClient(baseUrl: 'http://api.example.com')
          .allowsCredentialSubmission,
      isFalse,
    );
  });
}
