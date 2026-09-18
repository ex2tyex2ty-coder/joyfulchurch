"""Session-local chat snapshots with push-first, bounded catch-up reads."""
from audio_requests import AudioError, AudioAccessError

HEALTHY_CHECK_SECONDS = 21
FALLBACK_CHECK_SECONDS = 3


def accept_event(state, event, scope, now):
    if not isinstance(event, dict) or event.get('scope') != scope:
        return False
    marker = (event.get('client'), event.get('seq'))
    if marker == state.get('event_marker'):
        return False
    state['event_marker'] = marker
    changes = (event.get('client'), event.get('changes', 0))
    if changes != state.get('change_marker'):
        state['next_check'] = 0
        state['change_marker'] = changes
    status = event.get('status', 'offline')
    previous = state.get('transport')
    state['transport'] = status
    state['transport_at'] = now
    if status in {'changed', 'connected', 'catchup'}:
        state['next_check'] = 0
    elif status in {'offline', 'fallback', 'auth'} and previous != status:
        state['next_check'] = 0
    return True


def transport_healthy(state, now):
    return state.get('transport') in {'connected','changed','healthy'} and now-state.get('transport_at', 0) < 45


def read_snapshot(store, state, *, identity, desk, engineer_until, now, force=False):
    if desk and engineer_until <= now:
        state.clear()
        state.update(stopped=True, error='음향석 접속 시간이 끝났어요. 다시 로그인해 주세요.')
        return None
    if state.get('stopped') and not force:
        return state.get('snapshot')
    snapshot = state.get('snapshot')
    if snapshot and (snapshot[0]['closed'] or snapshot[0]['expires_at'] <= now) and not force:
        state['stopped'] = True
        return snapshot
    if not force and state.get('transport') == 'paused':
        return snapshot
    if not force and now < state.get('next_check', 0):
        return snapshot
    interval = HEALTHY_CHECK_SECONDS if transport_healthy(state, now) else FALLBACK_CHECK_SECONDS
    try:
        stamp = store.conversation_stamp(room_id=identity, engineer_until=engineer_until) if desk else store.conversation_stamp(participant_token=identity)
        if force or snapshot is None or stamp != state.get('stamp'):
            snapshot = store.conversations(identity) if desk else store.my_conversation(identity)
            state['snapshot'], state['stamp'] = snapshot, stamp
        state.update(checked_at=now, next_check=now+interval, failures=0, error='', stopped=False)
        if snapshot[0]['closed'] or snapshot[0]['expires_at'] <= now:
            state['stopped'] = True
        return snapshot
    except AudioAccessError as exc:
        state.update(stopped=True, error=str(exc))
        state.pop('snapshot', None)
        return None
    except AudioError as exc:
        failures = min(state.get('failures', 0)+1, 5)
        state.update(error=str(exc), failures=failures, next_check=now+min(30, 3*2**(failures-1)))
        return snapshot
