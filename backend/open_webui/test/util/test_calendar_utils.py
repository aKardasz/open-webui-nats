from datetime import datetime, timedelta

from open_webui.utils.calendar import expand_recurring_event


def _ns(dt: datetime) -> int:
	return int(dt.timestamp() * 1_000_000_000)


def test_expand_recurring_event_returns_original_when_no_rrule():
	start = datetime.utcnow()
	event = {
		'id': 'evt-1',
		'start_at': _ns(start),
		'end_at': _ns(start + timedelta(hours=1)),
		'rrule': None,
	}

	result = expand_recurring_event(event, _ns(start), _ns(start + timedelta(days=1)))
	assert result == [event]


def test_expand_recurring_event_expands_daily_rrule_with_instance_ids():
	start = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
	event = {
		'id': 'evt-1',
		'start_at': _ns(start),
		'end_at': _ns(start + timedelta(hours=1)),
		'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1',
	}

	result = expand_recurring_event(
		event,
		_ns(start),
		_ns(start + timedelta(days=3)),
	)

	assert len(result) >= 2
	assert all('instance_id' in item for item in result)
	assert result[0]['start_at'] >= event['start_at']
	assert result[1]['start_at'] > result[0]['start_at']
