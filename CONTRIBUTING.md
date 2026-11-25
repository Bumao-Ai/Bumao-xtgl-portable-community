# 贡献指南（Contributing）

欢迎提交 Issue 与 Pull Request。本项目采用 **DCO（Developer Certificate of Origin）1.1**，全文见仓根 [`DCO`](DCO)：提交者须声明有权提交该贡献，并在每次提交中携带签署行。

## 签署方式

每个提交用 `-s` 自动追加签署行：

```
git commit -s -m "你的提交说明"
```

生成的签署行格式：

```
Signed-off-by: 名字 <邮箱>
```

签署行必须使用提交者的真实姓名与可联系邮箱，且与 `git config user.name`／`user.email` 一致。忘记签署时，可用 `git commit --amend -s --no-edit` 补签（仅限尚未推送的提交）。

## PR 前自检

- [ ] 所有提交均已签署 DCO（`Signed-off-by:` 行存在）；
- [ ] 本地 `check --strict` 通过（按改动所属端执行对应入口）；
- [ ] 未提交 `.bak`、`__pycache__`、本机路径、内网地址、真实姓名等敏感内容；
- [ ] 新增源文件头含 Apache-2.0 短声明与 `SPDX-License-Identifier: Apache-2.0`；
- [ ] 改动说明写清「改了什么、为什么改、如何验证」。

## 许可

贡献一经合并，即按仓根 [Apache License 2.0](LICENSE) 授权。本项目**暂不引入 CLA**；企业合作或特殊授权另行商议。
