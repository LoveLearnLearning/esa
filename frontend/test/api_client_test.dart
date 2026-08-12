import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';

void main() {
  test('default API endpoint never exposes the backend HTTP address', () {
    final baseUrl = ApiClient().baseUrl;

    expect(baseUrl, kIsWeb ? '/api' : 'https://esa.lovelearnlearning.cn/api');
    expect(baseUrl, isNot(contains('115.29.197.244')));
    expect(baseUrl, isNot(startsWith('http://')));
  });

  test('explicit API endpoint has its trailing slash normalized', () {
    expect(
      ApiClient(baseUrl: 'https://example.com/api/').baseUrl,
      'https://example.com/api',
    );
  });
}
