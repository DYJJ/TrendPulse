/// 帖子数据模型
class Post {
  final String id;
  final String source;
  final String? title;
  final String content;
  final String? author;
  final String? url;
  final DateTime? timestamp;
  final Interactions interactions;

  Post({
    required this.id,
    required this.source,
    this.title,
    required this.content,
    this.author,
    this.url,
    this.timestamp,
    required this.interactions,
  });

  factory Post.fromJson(Map<String, dynamic> json) {
    return Post(
      id: json['id'] as String,
      source: json['source'] as String,
      title: json['title'] as String?,
      content: json['content'] as String,
      author: json['author'] as String?,
      url: json['url'] as String?,
      timestamp: json['timestamp'] != null
          ? DateTime.parse(json['timestamp'] as String)
          : null,
      interactions: Interactions.fromJson(
        json['interactions'] as Map<String, dynamic>,
      ),
    );
  }
}

/// 互动数据模型
class Interactions {
  final int likes;
  final int comments;
  final int shares;

  Interactions({
    required this.likes,
    required this.comments,
    required this.shares,
  });

  factory Interactions.fromJson(Map<String, dynamic> json) {
    return Interactions(
      likes: json['likes'] as int,
      comments: json['comments'] as int,
      shares: json['shares'] as int,
    );
  }
}

/// 帖子列表分页响应
class PostListResponse {
  final List<Post> posts;
  final int total;
  final int page;
  final int pageSize;

  PostListResponse({
    required this.posts,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  factory PostListResponse.fromJson(Map<String, dynamic> json) {
    return PostListResponse(
      posts: (json['posts'] as List)
          .map((e) => Post.fromJson(e as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
    );
  }
}
