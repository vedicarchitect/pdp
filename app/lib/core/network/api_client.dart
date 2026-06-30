import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';

import '../config/app_config.dart';

/// Thin REST wrapper around [Dio], bound to the configured backend base URL.
class ApiClient {
  ApiClient({Dio? dio, String? baseUrl})
      : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: baseUrl ?? AppConfig.current.apiBase,
                connectTimeout: const Duration(seconds: 8),
                receiveTimeout: const Duration(seconds: 8),
              ),
            );

  final Dio _dio;

  /// GETs [path] (e.g. `/api/v1/portfolio/summary`) and returns a JSON object.
  Future<Map<String, dynamic>> getJson(String path) async {
    final res = await _dio.get<dynamic>(path);
    final data = res.data;
    if (data is Map<String, dynamic>) return data;
    if (data is String && data.isNotEmpty) {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) return decoded;
    }
    throw const FormatException('Expected a JSON object response');
  }

  /// PATCHes [path] with [body] and returns a JSON object.
  Future<Map<String, dynamic>> patchJson(String path, {required Map<String, dynamic> body}) async {
    final res = await _dio.patch<dynamic>(path, data: body);
    final data = res.data;
    if (data is Map<String, dynamic>) return data;
    if (data is String && data.isNotEmpty) {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) return decoded;
    }
    throw const FormatException('Expected a JSON object response');
  }

  /// POSTs to [path] with [body] and returns a JSON object.
  Future<Map<String, dynamic>> postJson(String path, {Map<String, dynamic>? body}) async {
    final res = await _dio.post<dynamic>(path, data: body);
    final data = res.data;
    if (data is Map<String, dynamic>) return data;
    if (data is String && data.isNotEmpty) {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) return decoded;
    }
    throw const FormatException('Expected a JSON object response');
  }

  /// DELETEs [path] and returns a JSON object.
  Future<Map<String, dynamic>> deleteJson(String path) async {
    final res = await _dio.delete<dynamic>(path);
    final data = res.data;
    if (data is Map<String, dynamic>) return data;
    if (data is String && data.isNotEmpty) {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) return decoded;
    }
    throw const FormatException('Expected a JSON object response');
  }

  /// PUTs to [path] with [body] and returns a JSON object.
  Future<Map<String, dynamic>> putJson(String path, {required Map<String, dynamic> body}) async {
    final res = await _dio.put<dynamic>(path, data: body);
    final data = res.data;
    if (data is Map<String, dynamic>) return data;
    if (data is String && data.isNotEmpty) {
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) return decoded;
    }
    throw const FormatException('Expected a JSON object response');
  }
}

