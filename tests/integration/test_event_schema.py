"""PostgreSQL constraints for source and user event period versions."""

from datetime import UTC, date, datetime, time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 1, 15, tzinfo=UTC)


def test_event_period_layers_coexist_and_reject_inconsistent_intervals(
    integration_database_url: str,
) -> None:
    engine = create_engine(integration_database_url)
    opportunity_id = uuid4()
    observation_id = uuid4()
    source_set_id = uuid4()
    user_set_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO opportunity (
                        id, kind, creation_origin, created_at, updated_at
                    ) VALUES (
                        :id, 'EVENT', 'SOURCE', :now, :now
                    )
                    """
                ),
                {"id": opportunity_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event (
                        id, source_title, source_types, declared_status,
                        source_links, source_business_signals,
                        first_observed_at, last_observed_at, created_at, updated_at
                    ) VALUES (
                        :id, 'Fête locale', '["Festival"]'::jsonb, 'UNKNOWN',
                        '[]'::jsonb, '{}'::jsonb,
                        :now, :now, :now, :now
                    )
                    """
                ),
                {"id": opportunity_id, "now": NOW},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO source_observation (
                        id, data_source_code, retrieved_at, adapter_version,
                        schema_version, content_fingerprint, payload, validation_status
                    ) VALUES (
                        :id, 'DATATOURISME_API', :now, 'datatourisme-v1-events-v1',
                        'datatourisme-event-candidate-v1', :fingerprint,
                        '{}'::jsonb, 'VALID'
                    )
                    """
                ),
                {
                    "id": observation_id,
                    "now": NOW,
                    "fingerprint": "a" * 64,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period_set (
                        id, event_id, layer, source_observation_id,
                        is_current, created_at
                    ) VALUES (
                        :source_id, :event_id, 'SOURCE', :observation_id, TRUE, :now
                    ), (
                        :user_id, :event_id, 'USER', NULL, TRUE, :now
                    )
                    """
                ),
                {
                    "source_id": source_set_id,
                    "user_id": user_set_id,
                    "event_id": opportunity_id,
                    "observation_id": observation_id,
                    "now": NOW,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        start_time, end_time, interpretation_timezone,
                        precision, recurrence, source_path, created_at
                    ) VALUES (
                        :id, :set_id, 0, :start_date, :end_date,
                        :start_time, :end_time, 'Europe/Paris',
                        'DATE_AND_TIME', '{}'::jsonb, 'takesPlaceAt[0]', :now
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "set_id": source_set_id,
                    "start_date": date(2026, 10, 10),
                    "end_date": date(2026, 10, 12),
                    "start_time": time(10),
                    "end_time": time(18),
                    "now": NOW,
                },
            )
            current_layers = (
                connection.execute(
                    text(
                        """
                    SELECT layer
                    FROM event_period_set
                    WHERE event_id = :event_id AND is_current
                    ORDER BY layer
                    """
                    ),
                    {"event_id": opportunity_id},
                )
                .scalars()
                .all()
            )
            overlaps = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM event_period
                    WHERE daterange(
                        start_date,
                        COALESCE(end_date, start_date),
                        '[]'
                    ) && daterange(:start_date, :end_date, '[]')
                    """
                ),
                {"start_date": date(2026, 10, 11), "end_date": date(2026, 10, 11)},
            ).scalar_one()

        assert current_layers == ["SOURCE", "USER"]
        assert overlaps == 1

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO event_period_set (
                        id, event_id, layer, source_observation_id,
                        is_current, created_at
                    ) VALUES (
                        :id, :event_id, 'SOURCE', :observation_id, TRUE, :now
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "event_id": opportunity_id,
                    "observation_id": observation_id,
                    "now": NOW,
                },
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO event_period (
                        id, period_set_id, display_order, start_date, end_date,
                        start_time, end_time, interpretation_timezone,
                        precision, recurrence, source_path, created_at
                    ) VALUES (
                        :id, :set_id, 1, :day, NULL,
                        :start_time, :end_time, 'Europe/Paris',
                        'DATE_AND_TIME', '{}'::jsonb, 'takesPlaceAt[1]', :now
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "set_id": source_set_id,
                    "day": date(2026, 10, 10),
                    "start_time": time(18),
                    "end_time": time(12),
                    "now": NOW,
                },
            )
    finally:
        engine.dispose()
