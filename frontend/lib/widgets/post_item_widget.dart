import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:trendpulse/models/post.dart';
import 'package:trendpulse/utils/time_format.dart';

/// 帖子卡片 - Apple 列表行风格
class PostItemWidget extends StatelessWidget {
  final Post post;
  const PostItemWidget({super.key, required this.post});

  Color _sourceColor() {
    switch (post.source) {
      case 'reddit': return const Color(0xFFFF6723);
      case 'youtube': return const Color(0xFFFF2D55);
      case 'twitter': return const Color(0xFF0A84FF);
      default: return const Color(0xFF8E8E93);
    }
  }

  IconData _sourceIcon() {
    switch (post.source) {
      case 'reddit': return Icons.forum_rounded;
      case 'youtube': return Icons.play_circle_rounded;
      case 'twitter': return Icons.tag_rounded;
      default: return Icons.language_rounded;
    }
  }

  Future<void> _openUrl() async {
    if (post.url == null) return;
    final uri = Uri.tryParse(post.url!);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sc = _sourceColor();
    return InkWell(
      onTap: post.url != null ? _openUrl : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 来源图标
            Container(
              width: 36, height: 36,
              decoration: BoxDecoration(
                color: sc.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(_sourceIcon(), size: 18, color: sc),
            ),
            const SizedBox(width: 12),
            // 内容
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // 标题
                  if (post.title != null && post.title!.isNotEmpty)
                    Text(
                      post.title!,
                      style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, height: 1.3),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  if (post.title != null && post.title!.isNotEmpty) const SizedBox(height: 3),
                  // 内容
                  Text(
                    post.content,
                    style: const TextStyle(fontSize: 14, color: Color(0xFF8E8E93), height: 1.4),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 6),
                  // 元信息
                  Row(
                    children: [
                      Text(
                        post.source,
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: sc),
                      ),
                      if (post.author != null) ...[
                        const Text(' · ', style: TextStyle(fontSize: 12, color: Color(0xFF636366))),
                        Text(post.author!, style: const TextStyle(fontSize: 12, color: Color(0xFF636366))),
                      ],
                      if (post.timestamp != null) ...[
                        const Text(' · ', style: TextStyle(fontSize: 12, color: Color(0xFF636366))),
                        Text(
                          formatRelativeTime(post.timestamp!),
                          style: const TextStyle(fontSize: 12, color: Color(0xFF636366)),
                        ),
                      ],
                      const Spacer(),
                      _Stat(Icons.thumb_up_outlined, post.interactions.likes),
                      const SizedBox(width: 10),
                      _Stat(Icons.chat_bubble_outline, post.interactions.comments),
                    ],
                  ),
                ],
              ),
            ),
            // 箭头
            if (post.url != null)
              Padding(
                padding: const EdgeInsets.only(left: 8, top: 8),
                child: Icon(Icons.chevron_right_rounded, size: 20, color: const Color(0xFF48484A).withValues(alpha: 0.8)),
              ),
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final IconData icon;
  final int count;
  const _Stat(this.icon, this.count);

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 12, color: const Color(0xFF636366)),
        const SizedBox(width: 2),
        Text(
          count >= 1000 ? '${(count / 1000).toStringAsFixed(1)}k' : '$count',
          style: const TextStyle(fontSize: 12, color: Color(0xFF636366)),
        ),
      ],
    );
  }
}
