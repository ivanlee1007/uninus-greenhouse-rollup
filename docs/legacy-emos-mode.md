# Legacy EMOS compatibility (explicit opt-in)

`feedback_mode: standard` remains the default for all existing and newly created entries. There is no automatic detection, migration or fallback to compatibility mode. Native MQTT Covers are not modified.

For an EMOS device that publishes relay state only when it changes, an existing HA switch can remain `unknown` after restart. After physically confirming that the actuator is stopped, an administrator can open the **existing entry's Options**, choose **Legacy EMOS compatibility (command-estimated)** and explicitly acknowledge the separate risk confirmation. This is not a new integration entry or a firmware change.

## Admission and mode changes

- Switching either way requires stopped estimator/command/timer state, no queued direction/stop/fail-safe work, no unresolved stop error, and both source entities present and enabled. Known `on`, missing, disabled and `unavailable` sources block the change. `unknown` is permitted for this mode-selection operation; it is not interpreted as OFF.
- Mode, cover type and auto-stop Options are applied in place under the integration's policy and command ownership, without reload and without relay calls. Position and entity identity are preserved by a mode toggle. Reconfigure still reloads for name/source changes, but preserves the selected feedback mode.
- Enabling forces auto-stop on. Disabling it through Options or `set_auto_stop_at_travel_end` is rejected while legacy mode remains selected. Even a historically inconsistent saved false value cannot disable the runtime legacy timer. Numeric hardware settings still use the existing integration-owned Store; changing travel times invalidates the old position.
- Entry options use Home Assistant's normal delayed persistence, not a synchronous fsync guarantee. Numeric settings and nonnumeric options are separate authorities, not a cross-store transaction.

## Commands and estimates

- Only explicitly selected legacy mode permits **OFF service calls to both relays → configured dead time → ON service call**, without waiting for observed OFF. A successful service call proves neither physical OFF nor physical ON. Preserve independent hardware interlocks, limits and timers; HA, network and device failure can prevent a stop.
- Both source states must still exist, be enabled and not be unavailable immediately before new ON. Unknown is allowed; missing/unavailable/disabled is not. Failure to send either initial OFF prevents ON. Direction-start failure and cancellation attempt OFF for both sources; one failed OFF does not skip the other.
- Successful local ON starts a command-owned time estimator and mandatory stop budget. Partial targets retain the standard integer opening-position contract. Unknown positions reject intermediate targets without relay writes; explicit endpoints use the full direction-specific travel budget. Timer completion sends OFF to both sources and freezes the estimate without requiring an OFF echo.
- Cached feedback is not replayed as motion on startup or every tick. Delayed OFF reports cannot cancel a local command's stop budget. After a locally controlled source is stopped, its ON echoes remain quarantined until a separately observed idle OFF transition establishes a new external baseline (cached OFF does not clear the fence). A new external OFF→ON transition, with the other source known OFF, can then start external feedback-based estimation with its own forced timer; a subsequent OFF ends external estimation. Opposite-direction ON and both-ON feedback remain safety-relevant and request fail-safe OFF regardless of that fence. Source loss during a legacy run also requests fail-safe OFF.
- EMOS telemetry without sequence numbers cannot prove whether an apparently new OFF→ON edge is a delayed packet or a real external action. Unknown→ON and unchanged cached ON never restart estimation. Do not operate the relays through competing legacy automations; use the Cover services. These are estimates, not a physical position controller.

## State and restoration

`feedback_mode` is `standard` or `legacy_emos`. `position_basis` distinguishes `unknown`, `remembered`, `command_estimated` and `feedback_estimated`. `position_unverified` and `position_is_estimated` are true; `physical_arrival_confirmed` is always false. Legacy endpoints remain `estimated`, not physically calibrated. `timer_elapsed` in legacy mode means the budget expired and both OFF calls returned, **not** observed de-energizing or physical arrival. Stop failures expose `stop_command_error` and target errors where applicable.

RestoreEntity extra data retains full-precision position even while the Cover is unavailable, together with the existing travel-model compatibility checks. Startup marks a restored position `remembered`/unverified, attempts OFF, and never restores a direction, target or timer. The extra-data `motion_interrupted` flag records active/uncertain legacy motion in HA's most recently saved snapshot. Normal completed timer stops clear it. It is conservative after interruption and cannot certify the last instant before a sudden power cut; this uses HA's existing periodic/shutdown persistence, not a new crash-safe journal.

## Offline verification and supervised acceptance

The canonical gate is `uv run --python 3.14 --with homeassistant==<matrix version> python -m unittest discover -s tests_python -v`, then `python -m compileall -q custom_components` and `git diff --check`. CI retains the existing 2026.7.2/2026.10.2 dependencies and adds 2026.11.0, plus the unchanged hassfest and HACS jobs.

No live hardware acceptance is implied by these offline tests. Before production use, with one physically supervised actuator and independent emergency stop:

1. Confirm correct real-output mapping (not EMOS virtual sequence switches), travel times, independent direction interlock and hardware stop protection.
2. With both relays physically OFF and HA sources unknown, enable legacy mode through Options and acknowledge the risk. Verify **no relay actuation on either mode toggle**, unchanged entity identity and remembered fractional position.
3. Exercise open, stop, reverse and a short intermediate target. Measure OFF/dead-time/ON order and the timer's OFF attempts despite absent echoes; verify no claim of measured arrival.
4. Inject delayed telemetry, a valid external edge, opposite ON/both ON, missing/unavailable source and a failed OFF. Verify protective stop attempts, visible uncertainty and no old command resuming.
5. Restart HA during movement in a controlled setup. Verify startup OFF, remembered/unverified position, no resumed motion or target, and conservative interrupted status if the prior active snapshot was saved.
6. Return to standard mode while idle and verify the observed-OFF interlock is again required. Do not approve unattended operation if physical interlocks or emergency stop cannot be verified.
