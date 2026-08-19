import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

Future<bool> downloadAttachment({
  required Uint8List bytes,
  required String filename,
  required String mediaType,
}) async {
  final body = web.document.body;
  if (body == null) return false;
  final blob = web.Blob(
    [bytes.toJS].toJS,
    web.BlobPropertyBag(type: mediaType),
  );
  final url = web.URL.createObjectURL(blob);
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = filename
    ..style.display = 'none';
  body.append(anchor);
  anchor.click();
  anchor.remove();
  web.URL.revokeObjectURL(url);
  return true;
}
