# Feed share attribution

Explicit share/copy requests use the authenticated sharer's persisted referral code:

- Mini App `/mini-app/api/feed/share` and `/api/v1/feed/{gen_id}/link` use the user from validated Telegram initData
- All response URL variants use the same sharer. The video compatibility adapter changes the navigation route while preserving that suffix
- Bot Feed CopyText uses the owner of a private chat. Shared or unknown chats use `bfs:<id>` so each click resolves `callback.from_user.id`
- `bfs` supports both public Feed and profile-visible publications, and rejects hidden/withdrawn content
- Missing sharer codes produce a plain content link. Author codes, supplied request codes and chat IDs are never a substitute
- Per-viewer responses remain `Cache-Control: no-store`; cached cards are not changed

The generation ID, card author and `source_feed_gen_id` remain the original source. Creator repeat rewards use that source's owner. Invitation attribution continues to use the existing referral eligibility, first-referrer and idempotency rules. Sharing creates no new permission or partner approval and does not reassign existing referrals, change rates, or adjust past payments.

Owner-publication confirmations and author-profile identity links keep their existing owner identity. Internal Repeat/Open navigation is unchanged. Existing issued URLs remain valid with their embedded code; this change affects newly requested share links only. Existing Telegram CopyText buttons keep their embedded URLs until the feed is reopened or navigated and the keyboard is rebuilt.

Regression coverage: `tests/test_feed_share_attribution.py` exercises signed HTTP requests, all link variants, different successive sharers, Feed/Profile permissions, invalid signatures, missing codes, Telegram callbacks/keyboards, shared chats, and creator-reward ownership/idempotency using isolated SQLite. No paid provider or production-data test is required.
