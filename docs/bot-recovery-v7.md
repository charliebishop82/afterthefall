# Bot recovery policy v7

Status: installed after the user's full suite completed. No tests run. Python AST syntax checks passed. Full discovery will automatically include test_bot_recovery.py after installation; the quick suite remains deliberately curated.

Changes use normal player commands and preserve personality probabilities for exploration and military actions. Sustained negative Water/Food flow can trigger additional staffing or another eligible producer even if that type is already owned. Only one construction/upgrade/repair project is planned at once. Town Hall administrators are not treated as ordinary production workers.

When a planned material purchase cannot fit because shared material storage is full, bots may sell up to 25 excess materials while protecting that project's cost, ordinary material reserves, unavailable/reserved stock and queued/active manufacturing inputs. Near-full-stock selling can also handle zero reported production at capacity. No resources, Credits, market stock or daily allowance are created by the controller.

Workers assigned to paused scavenging outside safe oxygen coverage are released through the normal scavenging endpoint. Existing policy can reassign them to safe sites or other eligible work. This increment does not automatically plan a chain of oxygen expansion buildings; lack of safe sites is reported as a specific waiting reason instead. Idle reasons also identify full storage, no free citizens, negative supply flow and unavailable shared/daily Metal or Electronics. They are diagnostic constraints, not proof every possible strategy has been exhausted.

Restart only run_bots.py so it loads recovery-v7; the unchanged player/admin APIs and database need no restart. Existing bot traces include the policy version so before/after behavior can be compared.
