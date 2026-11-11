#!/usr/bin/env bash
# Preserve immutable Next.js VK JS/CSS chunks referenced by clients holding
# a cached HTML document from an older release. Never overwrite new chunks.
set -Eeuo pipefail

[[ $# -eq 2 ]] || { echo 'Usage: retain_vk_immutable_assets.sh old_static new_static' >&2; exit 2; }
old_static=$1
new_static=$2
[[ -d $new_static ]] || { echo 'New VK static export is absent' >&2; exit 3; }
if [[ ! -d $old_static ]]; then
  echo 'No previous VK static assets; initial deployment'
  exit 0
fi

# Old and new exports have content-addressed filenames. Abort on conflicting
# immutable paths to avoid serving a mismatched build to existing clients.
while IFS= read -r -d '' old; do
  relative=${old#"$old_static"/}
  new="$new_static/$relative"
  if [[ -e $new ]] && ! cmp -s -- "$old" "$new"; then
    echo "VK asset path collision: $relative" >&2
    exit 4
  fi
done < <(find "$old_static" -type f -print0)

rsync -a --ignore-existing --chmod=D755,F644 -- "$old_static/" "$new_static/"
echo 'Retained prior immutable VK assets for cached WebViews'
