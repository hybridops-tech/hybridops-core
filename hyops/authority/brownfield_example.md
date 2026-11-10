# Authority Transition: Brownfield Scenario Example

This document illustrates the authority-transition semantics for emergency reconciliation in a real brownfield infrastructure scenario.

## Scenario: Network Configuration Drift in Production

**Initial State:**
- Declared intent: Network route configured in controller definition
- Live device: Same route running correctly
- Controller cache: Knows about the route

**Emergency Event:**
Network operator manually changes route on live device due to urgent production issue (out-of-band change):
```
Live device: 10.0.0.0/8 via 192.168.1.254 (manual emergency fix)
Declared intent: 10.0.0.0/8 via 192.168.1.1 (original config)
Controller cache: 10.0.0.0/8 via 192.168.1.1 (hasn't refreshed yet)
```

## Authority Transition Decision

### Detection Phase
1. **Observation Collection:**
   - Query declared intent: Route 10.0.0.0/8 via 192.168.1.1
   - Query live device: Route 10.0.0.0/8 via 192.168.1.254
   - Query controller cache: Route 10.0.0.0/8 via 192.168.1.1

2. **Disagreement Detection:**
   ```python
   detected_disagreement = detect_observation_disagreement(
       declared=declared_authority,
       controller_cache=cached_observation,
       live_device=live_observation
   )
   # Result: DISAGREEMENT_DETECTED
   ```

### Freshness Evaluation
3. **Check Observation Freshness:**
   - Live device observation: Fresh (just polled)
   - Controller cache: Stale (last refresh 2 hours ago)
   - Declared intent: Always authoritative

   ```python
   is_live_fresh = is_observation_fresh(
       live_observation, 
       max_age_seconds=300
   )
   # Result: True (polled 15 seconds ago)
   
   is_cache_fresh = is_observation_fresh(
       controller_cache,
       max_age_seconds=300  
   )
   # Result: False (2 hours old)
   ```

### Provisional Decision
4. **Make Provisional-Use Decision:**
   ```python
   decision = decide_provisional_use(
       declared_authority="declared_route",
       live_observation=live_observation,  # Fresh, disagrees with declared
       cache_observation=controller_cache,  # Stale
       policy=AuthorityTransitionPolicy(
           allow_provisional_use=True,
           require_explicit_decision=True,
           max_provisional_duration_s=600,  # 10 minutes
           failure_mode="REVERT_TO_DECLARED",
           record_unverifiable=False
       ),
       authorization_context={
           "operator": "on-call-engineer",
           "reason": "Production emergency - packet loss to route target",
           "approval": "verbal - incident ticket #12345"
       }
   )
   ```

5. **Decision Result:**
   - **Type:** PROVISIONAL_USE_ALLOWED
   - **Rationale:** Live observation is fresh and represents working emergency mitigation
   - **Authorized Operations:** Read, monitor, verify
   - **Forbidden Operations:** Revert without manual authorization
   - **Duration:** 10 minutes (operator must confirm or revert)

### Transition Record
6. **Create Transition Record:**
   ```python
   record = create_transition_record(
       declared_authority=declared_authority,
       controller_cache=controller_cache,
       live_device_state=live_observation,
       detected_disagreement=detected_disagreement,
       transition_decision=decision,
       transition_type=TransitionType.PROVISIONAL_USE,
       return_to_declared_at=datetime.now() + timedelta(seconds=600)
   )
   ```

   **Record Contains:**
   - Timestamp of each observation
   - Source of each state (declared/cache/live)
   - Freshness indicators
   - Explicit decision and authorization
   - Allowed and forbidden operations
   - Scheduled return to declared intent

## Recovery Actions

### During Provisional Period (10 minutes)
- **Monitoring:** Continuous health checks on both routes
- **Allowed:** Read live device state, verify connectivity
- **Forbidden:** Automatically revert route

### After Provisional Period
- **Automatic Check:** Has operator confirmed the emergency fix?
- **If Confirmed:** Extend provisional period or update declared intent
- **If Not Confirmed:** Revert to declared intent automatically
  ```python
  if is_provisional_expired(transition_record):
      if not is_confirmed_by_operator(authorization_context):
          revert_to_declared_intent(declared_authority)
          record_return_to_declared(record, "provisional_period_expired")
  ```

## Governance Guarantees

1. **Declared intent always remains authoritative** - recorded and can be enforced
2. **Live state changes are observable** - detected and evidence-recorded
3. **Provisional use is explicit** - requires approval, bounded in time
4. **Recovery is deterministic** - clear conditions for return to declared
5. **Evidence is preserved** - full transition record for audit/learning

## Integration Points

- Authority providers implement `decide_provisional_use()` callback
- Run records include `AuthorityTransitionRecord` for audit trail
- Dashboard surfaces active provisional transitions
- Alerts fire if provisional period approaches expiration
- Compliance reports include all emergency reconciliations
