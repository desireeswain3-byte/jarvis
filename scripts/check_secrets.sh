#!/bin/sh
# Refuses to push if anything that looks like a key or personal file is about to go public.
cd "$(git rev-parse --show-toplevel)" || exit 1
bad=0
if git ls-files | grep -Eq '(^|/)(\.env|ME\.md|journal\.jsonl)$|memory/trading/lessons/'; then echo "BLOCKED: a private file is tracked"; bad=1; fi
if git grep -nEI '(sk-ant-[A-Za-z0-9_-]{10,}|sk_[a-f0-9]{30,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|PK[A-Z0-9]{18,})' >/dev/null; then echo "BLOCKED: something looks like an API key"; bad=1; fi
[ $bad -eq 0 ] && echo "secret check passed"
exit $bad
