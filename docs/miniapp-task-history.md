# Studio history and older publication settings

Studio initially shows the eight tasks from the polled bootstrap. **Загрузить ещё** appends older owned works without a maximum total-history count. Photos, videos and other ordinary tasks share the history; Genjutsu retains its separate run history. Creating or publishing a video through Telegram does not remove its generation record from Studio.

Open an older completed work and use **Настроить публикацию** to edit its existing publication and reference permissions, then **Сохранить публикацию**. Loading history does not publish, regenerate, charge, or change any reference choice. Existing owner permissions and hidden-recipe protections also apply to older pages.

`POST /mini-app/api/task-history` authenticates through the shared Mini App context. The optional `cursor` is the final task ID from the previous page; `recent_tasks` contains at most eight cards and `next_cursor` is another task ID or null. Results use the same serializer and privacy sanitizer as bootstrap. Stable descending `(created_at, id)` keysets avoid offset shifts when tasks are inserted or timestamps match. Missing, deleted and foreign anchors identically restart at the authenticated owner's head (`cursor_reset=true`); malformed cursors return 400. Body-supplied actor IDs never select an owner. Successful responses are `Cache-Control: no-store`.

The frontend keeps loaded pages across bootstrap refreshes, deduplicates IDs and merges confirmed selected-task detail/publication changes. Switching accounts or unmounting cancels the outstanding request. Page reads have a 10-second deadline; failure preserves the cursor and previously loaded cards for retry. No poll is started for every historical card.

Telemetry records authenticated Telegram ID, returned count, continuation/reset flags and elapsed milliseconds, without prompts, reference URLs or authentication data. No schema migration or business configuration is required; eight is a transport page size, not a creation or publication limit.
