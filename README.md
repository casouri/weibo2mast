# 微博转发毛象bot

支持图片视频，需要服务器（或者自己的电脑）运行。魔改自[weibo crawler](https://github.com/dataabc/weibo-crawler)。

毛象不能传太长的文字（默认500字，取决于实例的设置）和太大的图片（8MB）或视频（40MB），超出限制的文字会截断，超出限制的图片和视频就不传了。（长微博分段发毛象看起来挺乱的，所以直接截断了。）

## 安装

确保Python 3已安装。

```shell
git clone https://github.com/casouri/weibo2mast.git
cd weibo2mast
python -m pip install -r requirements.txt
```

## 配置

1. 配置跟踪的用户
- 首先根据这个说明拿到`user_id`：[《如何获取user_id》](https://github.com/dataabc/weibo-crawler#如何获取user_id)。
- 打开`config.json`，你应该看到类似的默认配置：
```json
{
  "user_list": [
    {
      "id": 6048193311,
      "comment": "速报"
    },
    {
      "id": 6578279612,
      "comment": "任地域"
    }
  ],
  "mastodon_instance_url": "https://mastodon.social",
  "toot_len_limit": 500,
  "max_attachment_count": 4,
  "include_repost": true,
  "include_post_url": false,
  "standalone_repost": true,
}
```
- 把`"user_list"`里`"id"`对应的值改成你想要跟踪的`user_id`。
- 把`"mastodon_instance_url"`改成你的bot存在的实例地址。
- `"toot_len_limit"`是实例的字数限制。
- `"max_attachment_count"`是实例的附件数量限制。
- 如果`"include_repost"`是`true`，bot会转发原创和转发微博，`false`的话只转发原创微博。
- 如果`"standalone_repost"`是`true`，bot会把转发微博和转发微博转发的微博分开转发，`false`的话会合在一起转发。（转发微博对应的嘟嘟会回复转发微博转发的微博对应的嘟嘟w）
- 如果`"include_post_url"`是`"true"`，bot会在转发的时候附上原微博的地址。

上面说的`"include_repost"`、`"standalone_repost"`也可以为某个用户单独设置，比如我不想转发这个用户的转发微博：

```json
{
  "id": 6048193311,
  "comment": "速报",
  "include_repost": false
}
```

2. 建立bot帐号
- 新建bot帐号，在设置里选`</> 开发`——`创建新应用`，权限只需要`read`和`write`，点`提交`。
- 成功以后点进新的app里，把`你的访问令牌`对应的一串字符复制下来。

3. 建立微博帐号和毛象帐号的对应关系

本bot支持一个微博帐号对应一个毛象帐号，或多个微博帐号对应一个毛象帐号。具体方法如下：
- 新建`token.json`文件。以这个模板填充内容：
```json
[
  {
    "id": "6132597268",
    "comment": "老袋",
    "token": "xxxx"
  },
  {
    "id": "6048193311",
    "comment": "知任",
    "token": "yyyy"
  },
  {
    "id": "6578279612",
    "comment": "任地域",
    "token": "yyyy"
  }
]
```

`id` 和之前一样，是微博帐号的id，`token`就是`你的访问令牌`，代表毛象帐号。放在一起的意思就是把id为这个的微博帐号转发到令牌为这个的毛象帐号。

注意，毛象的令牌相当于于密码，所以__不要上传或分享`token.json`__。

## 运行

```shell
python xpost.py
```

## 注

如果bot卡在一个微博上，估计是因为Mastodon的限流，耐心等待即可。bot转发失败三次就会放弃，如果发现漏了微博估计是因为这个。
