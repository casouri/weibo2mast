# 微博转发毛象bot

支持图片视频，需要服务器（或者自己的电脑）运行。修改自[weibo crawler](https://github.com/dataabc/weibo-crawler)。

## 安装

确保Python3已安装。

```shell
git clone xxx
cd xxx
python -m pip install -r requirements.txt
```

## 配置

1. 配置跟踪的用户
- 首先根据这个说明拿到`user_id`：[如何获取user_id](https://github.com/dataabc/weibo-crawler#如何获取user_id)。
- 然后打开`config.json`，把`"user_id_list"`改成你想要跟踪的`user_id`。这部份可以参考[程序设置](https://github.com/dataabc/weibo-crawler#3程序设置)。

2. 新建bot帐号，在设置里选`</> 开发`，`创建新应用`，权限只需要`write`，点`提交`。把`你的访问令牌`对应的一串字符复制下来，新建`token.txt`文件，粘贴，保存。

## 运行

```shell
python xpost.py
```

## 其他细节

– 我把`config.json`设置成了抓取所有微博，包括原创和转发，如果只想要原创，把`config.json`里`"filter"`对应的值改成`1`。

– `config.json`里除了`"user_id_list"`和`"filter"`以外其他的选项都没有效果（因为我魔改了），放着不动就行。
