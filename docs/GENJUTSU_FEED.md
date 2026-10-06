# Genjutsu: ordinary Feed publication and private repeat

A signed-in user can publish a final video from their own completed Genjutsu run to the ordinary Feed. Each selected output is copied into durable public Feed storage. Only the output becomes public; prompts, original source video and original photo references remain in the private Genjutsu recipe store.

## Publication contract

POST /mini-app/api/genjutsu with action=feed_publish accepts run_id, step_id, title and source_binding.

- source_binding=user requires each repeater to upload their own video
- source_binding=fixed retains the author's source video privately without offering replacement
- Photo slots preserve each reference's explicit user/fixed binding in the completed run snapshot
- Only final steps of fully completed runs may be published
- Recipe-derived runs cannot be republished as a new private recipe, including archived or legacy rows with a stale privacy flag
- The independent curated Trends recipe_publish action remains admin-only and requires its existing verified admin run

The response contains the ordinary public card and the existing public Recipe input contract. Feed cards include genjutsu_recipe_id and genjutsu_title. The card's prompt and reference arrays contain no private recipe data. Repeat opens the Genjutsu recipe picker rather than the generic video model form. Chains and variant counts are preserved, and the existing quote includes their full cost.

One publication is stored per final step. Concurrent identical requests converge on the same task and recipe. Changing the declaration returns feed_publication_conflict. A stale publish request after removal from discovery returns feed_publication_withdrawn; an explicit owner publication edit can restore the post.

## Shared links and video preview

New Telegram entry links use the same `feed_<id>_ref_<author>` route as ordinary videos. Already-issued `genjutsu_recipe_<id>` start parameters and `?genjutsu=1&genjutsu_recipe=<id>` URLs resolve through authenticated `recipe_preview` to the existing Feed/Profile video player. Opening a shared publication does not load the repeat form or quote it. The viewer explicitly presses Repeat after watching, then supplies their own declared photo/video slots.

`recipe_preview` returns only `{card: <public FeedItem>}`. Profile-only publications keep their Profile surface. Withdrawn, deleted, archived or inconsistent publication bindings fail closed; a missing card does not fall back to another video model. Only active curated recipes with no Feed-publication binding return `{card: null}` and retain their existing direct recipe entry. Owned run and admin studio entry remain unchanged.

The incoming route is consumed once. Closing a preview or repeat form does not reopen it on bootstrap refresh. Newer navigation and Back/Forward fence late resolution responses, while Telegram's normal removal of launch URL data does not discard the initial link. No private recipe plan, source video or original reference image is exposed by preview resolution.

## Visibility and repeat admission

Removing a post from discovery Feed while retaining its shared Profile leaves repeat available, following the existing publication contract. Full publication withdrawal blocks new recipe access, quote creation and launching an already-issued quote. Admission locks the publication row in the same transaction as reservation, so withdrawal cannot race the final permission check.

Already accepted runs retain their normal completion, delivery and financial behavior. This change adds no charges, rewards, provider calls or price rules.

Synthetic generation_tasks rows supply ordinary Feed/Profile cards and publication controls. They are excluded from the Mini App's generic recent task history, because the Genjutsu studio owns the actual run history. Legacy Telegram repeat buttons redirect to the recipe before billing; generic Mini App repeat calls return genjutsu_recipe_required.

## Storage, migration and verification

The additive genjutsu_feed_publications table binds each final step to its private recipe and ordinary Feed task. Startup uses the existing native SQLite/PostgreSQL DDL seam; schema_postgres.sql includes it in the schema transaction. No data backfill or new environment variable is needed.

Publication uses the configured private Genjutsu media root and existing public Feed directory/origin. It does not publish signed private media URLs. Public copies cannot recall a file already downloaded by a viewer; ordinary publication withdrawal has the same limitation.

Coverage includes authenticated publication, ownership, completed/final output, exact replacement slots/types, private provenance, unchanged bindings, concurrent idempotency, shared Profile visibility, full withdrawal, saved-quote rejection before reservation, already-accepted runs, safe task history, Telegram/generic-API routing and durable output copying. The PostgreSQL CI test exercises real SQL/boolean translation, concurrent publication, repeatable migration and withdrawal rollback. Local fixture tests never call paid providers or publish real user media.
