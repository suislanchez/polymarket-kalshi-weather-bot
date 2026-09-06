"""Task 13: unified read APIs and a safe manual paper-run route.

Five endpoints under /api/trading. Four read, one writes. The properties under
test are: no credential value ever reaches a response, there is no live-order
endpoint and no way to add one quietly, money crosses the boundary as strings,
the read models are projections rather than dumps, the run route refuses
everything it should and leaves nothing behind when it fails, and a run that
proposes nothing is a success.

Two notes on how this file is built, both of them deliberate.

The TestClient is constructed WITHOUT the context manager. Entering the
lifespan runs the real startup handler, which on a machine with Archives
mounted calls init_db() against the production ledger and starts the real
scheduler. A bare TestClient routes requests and honours dependency_overrides
without firing any of that.

The get_db override opens a FRESH session per request and every durability
assertion reads through a separate session built from the fixture's own
sessionmaker. A shared session would let a handler that never commits pass a
read-back, because the uncommitted row is visible in the writer's own identity
map. That is the shape of defect this project has shipped four times.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import main
from backend.config import settings
from backend.models.database import Base, TradingEvent, UnifiedOrder, get_db

TRADING_PREFIX = "/api/trading"

# Every credential-ish Settings field. Seeded with unique sentinels so a leak
# names the field it came from. Kept as an explicit reviewed list rather than a
# scan, because two credentials are read from os.getenv and never reach Settings.
CREDENTIAL_FIELDS = (
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_KEY_ID",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_API_PASSPHRASE",
    "RELAYER_API_KEY",
    "RELAYER_API_KEY_ADDRESS",
    "KALSHI_API_KEY_ID",
    "KALSHI_PRIVATE_KEY_PATH",
    "GROQ_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
)


def sentinel_for(field: str) -> str:
    """A long unique marker sharing no 4-gram with any other sentinel."""
    return f"QQ{field}QQ{'Z' * 8}{abs(hash(field)) % 10**8:08d}"


def ngrams(text: str, size: int = 4) -> set:
    return {text[i : i + size] for i in range(len(text) - size + 1)}


@pytest.fixture
def engine(tmp_path: Path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(factory):
    """A TestClient whose get_db yields a fresh session per request."""

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override
    test_client = TestClient(main.app)
    yield test_client
    main.app.dependency_overrides.clear()


@pytest.fixture
def paper_mode(monkeypatch):
    monkeypatch.setattr(settings, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", False)


@pytest.fixture
def seeded_credentials(monkeypatch):
    """Every credential set to a distinctive value, via the settings singleton.

    Never through os.environ: tests/test_trading_runtime.py asserts the Alpaca
    variables are absent from the environment, and a process-wide set would make
    that test fail depending on collection order.
    """
    seeded = {}
    for field in CREDENTIAL_FIELDS:
        value = sentinel_for(field)
        monkeypatch.setattr(settings, field, value, raising=False)
        seeded[field] = value
    return seeded


# ---------------------------------------------------------------------------
# The surface itself
# ---------------------------------------------------------------------------


def walk_routes(routes, prefix=""):
    """Enumerate every reachable path, including the method-less kinds.

    Mount and WebSocketRoute expose no .methods, so a methods-only comprehension
    omits them entirely. And a Mount's children carry paths RELATIVE to it, so
    the prefix has to accumulate: a mount at /api whose child is
    /trading/place-order serves POST /api/trading/place-order while appearing
    under neither name. Both route guards below use this, because a scan of only
    the top level misses a nested route in exactly the case the guards exist for.
    """
    for route in routes:
        path = prefix + getattr(route, "path", "")
        children = getattr(route, "routes", None)
        if children is not None:
            yield (path, "MOUNT")
            yield from walk_routes(children, path)
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            yield (path, "WEBSOCKET" if "WebSocket" in type(route).__name__ else "MOUNT")
        else:
            for method in sorted(set(methods) - {"HEAD", "OPTIONS"}):
                yield (path, method)


def test_the_trading_surface_is_exactly_the_declared_allowlist():
    """A route-table assertion, not a grep.

    The point is to fail when someone ADDS an endpoint, which is the only way a
    live-order route arrives. A substring scan of the source would miss a route
    registered dynamically or named innocuously.
    """
    trading_routes = {
        entry for entry in walk_routes(main.app.routes) if entry[0].startswith(TRADING_PREFIX)
    }

    assert trading_routes == {
        (f"{TRADING_PREFIX}/status", "GET"),
        (f"{TRADING_PREFIX}/orders", "GET"),
        (f"{TRADING_PREFIX}/events", "GET"),
        (f"{TRADING_PREFIX}/portfolio", "GET"),
        (f"{TRADING_PREFIX}/paper/run", "POST"),
    }


def test_no_route_anywhere_offers_live_order_placement():
    """Belt and braces across the whole app, not just the trading prefix."""
    forbidden = re.compile(r"live|real[-_]?order|submit[-_]?order|place[-_]?order", re.I)
    offenders = [
        path for path, _kind in walk_routes(main.app.routes) if forbidden.search(path)
    ]
    assert offenders == []


def test_entertainment_is_absent_from_the_unified_surface():
    entertainment = [
        getattr(route, "path", "")
        for route in main.app.routes
        if getattr(route, "path", "").startswith(TRADING_PREFIX)
        and "entertainment" in getattr(route, "path", "")
    ]
    assert entertainment == []


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_status_reports_credential_presence_as_booleans_only(
    client, paper_mode, seeded_credentials
):
    body = client.get(f"{TRADING_PREFIX}/status").json()

    credentials = body["credentials"]
    assert credentials, "status must report credential presence"
    for name, value in credentials.items():
        assert isinstance(value, bool), f"{name} must be a bool, got {type(value)!r}"


def test_no_credential_fragment_reaches_any_trading_response(
    client, paper_mode, seeded_credentials
):
    """The strong version of "no secrets in the API".

    A `sentinel in body` check passes while a redacted PREFIX of the secret sits
    in the response -- which is how the relayer route came to publish an address
    preview. Matching 4-grams catches the fragment, and unique sentinels mean a
    hit names the field it leaked from.
    """
    responses = [client.get(f"{TRADING_PREFIX}/{name}") for name in ("status", "orders", "events", "portfolio")]
    responses.append(client.post(f"{TRADING_PREFIX}/paper/run"))

    blob = "".join(response.text for response in responses)
    blob += "".join(json.dumps(dict(response.headers)) for response in responses)
    present = ngrams(blob)

    leaks = [
        field
        for field, value in seeded_credentials.items()
        if ngrams(value) & present
    ]
    assert leaks == [], f"credential fragments reached a response: {leaks}"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_reports_paper_mode_and_the_authoritative_kill_switch(
    client, paper_mode
):
    body = client.get(f"{TRADING_PREFIX}/status").json()

    assert body["execution_mode"] == "paper"
    assert body["paper_only"] is True
    assert body["kill_switch"]["engaged"] is False
    # Naming the source keeps an operator from flipping a flag nothing reads.
    # Both named flags gate; asserting one literal string was correct only while
    # GLOBAL_TRADING_KILL_SWITCH was inert.
    source = body["kill_switch"]["source"]
    assert "LIVE_TRADING_ENABLED" in source
    assert "GLOBAL_TRADING_KILL_SWITCH" in source


@pytest.mark.parametrize(
    "flag", ["LIVE_TRADING_ENABLED", "GLOBAL_TRADING_KILL_SWITCH"]
)
def test_every_flag_the_status_names_actually_engages_it(
    client, paper_mode, monkeypatch, flag
):
    """A named flag that leaves engaged False is the defect being prevented."""
    assert flag in client.get(f"{TRADING_PREFIX}/status").json()["kill_switch"]["source"]

    monkeypatch.setattr(settings, flag, True)

    assert client.get(f"{TRADING_PREFIX}/status").json()["kill_switch"]["engaged"] is True


def test_status_does_not_return_raw_archive_paths(client, paper_mode, monkeypatch):
    """Archive binding is reported as shape, not contents.

    archives_runtime_paths() puts the DATABASE_URL first and sqlite_path()
    returns a non-sqlite URL completely unchanged, so echoing that list would
    publish database credentials the day this runs on anything but sqlite.
    """
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql://bot:hunter2@db.internal:5432/trading"
    )

    response = client.get(f"{TRADING_PREFIX}/status")

    assert "hunter2" not in response.text
    assert "db.internal" not in response.text
    archives = response.json()["archives"]
    for name, value in archives.items():
        assert isinstance(value, bool), f"{name} must be a bool, got {type(value)!r}"


def test_status_reports_lane_flags_and_venue_states(client, paper_mode):
    body = client.get(f"{TRADING_PREFIX}/status").json()

    assert isinstance(body["lanes"], dict) and body["lanes"]
    for name, value in body["lanes"].items():
        assert isinstance(value, bool), f"lane {name} must be a bool"

    venues = {venue["venue"]: venue for venue in body["venues"]}
    assert "polymarket_paper" in venues
    assert "kalshi_paper" in venues
    # Scoped to the prediction venues, which is what the claim was always
    # about. "all venues are simulations" only held while Alpaca -- a real
    # paper broker -- was missing from the list entirely.
    for name in ("polymarket_paper", "kalshi_paper"):
        assert venues[name]["simulation"] is True, f"{name} must stay a simulation"
    assert venues["alpaca_paper"]["simulation"] is False


# ---------------------------------------------------------------------------
# Orders and events, driven through the real service
# ---------------------------------------------------------------------------


def route_one_real_order(session, *, metadata=None, rationale=None):
    """Drive a real weather proposal through the real PaperExecutionService.

    Hand-built UnifiedOrder rows would encode this author's beliefs about four
    things the schema actually decides -- that Decimals are strings, that
    occurred_at round-trips through a TypeDecorator, that the ORM attribute is
    order_metadata while the column is metadata, and that the identity columns
    are populated from the domain order rather than the report. Driving the
    real service asserts against the real shape.
    """
    from backend.core import scheduler as scheduler_module
    from backend.trading.risk import PortfolioState
    import tests.test_unified_scheduler as fixtures

    at = datetime.now(timezone.utc)
    signal = fixtures.make_signal("polymarket", timestamp=at)
    proposal = scheduler_module.build_weather_paper_proposal(
        signal, size=50.0, entry_price=0.56, created_at=at
    )
    assert proposal is not None
    if metadata is not None or rationale is not None:
        proposal = proposal.model_copy(
            update={
                key: value
                for key, value in (("metadata", metadata), ("rationale", rationale))
                if value is not None
            }
        )

    service = scheduler_module.build_paper_execution_service(session)
    assert service is not None
    context = scheduler_module.RiskContext(
        now=at,
        execution_mode="paper",
        idempotency_key=f"weather:{proposal.proposal_id}",
        weather_upstream_approved=True,
        weather_approval_evidence=scheduler_module.weather_upstream_evidence(signal),
    )
    portfolio = PortfolioState(
        equity=Decimal("10000"),
        start_of_day_nlv=Decimal("10000"),
        daily_realized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        crypto_exposure=Decimal("0"),
    )
    service.execute(
        proposal,
        portfolio=portfolio,
        context=context,
        limits=scheduler_module.paper_risk_limits(),
    )
    session.commit()
    return proposal


def test_orders_returns_money_fields_as_strings(client, factory, paper_mode):
    with factory() as session:
        route_one_real_order(session)

    body = client.get(f"{TRADING_PREFIX}/orders").json()

    assert len(body) == 1
    order = body[0]
    # The TYPE is the assertion. A float here still compares equal to the right
    # number while having already lost the precision the ledger preserved.
    for field in ("filled_quantity", "filled_notional", "average_fill_price"):
        assert isinstance(order[field], str), f"{field} must cross the boundary as a string"
    assert Decimal(order["filled_notional"]) == Decimal("49.99999984")
    assert Decimal(order["filled_quantity"]) == Decimal("89.285714")


def test_orders_never_dump_the_projection_metadata_column(
    client, factory, paper_mode
):
    """upsert_order_projection copies report metadata into the JSON column with
    no key filtering, so a dump would echo whatever reached it.

    The sentinel goes through the projection writer directly. Routing a proposal
    with hostile metadata proves nothing: PaperExecutionService replaces report
    metadata with a hard-coded literal before the projection is written, so the
    sentinel never reaches the column and the assertion holds for any handler.
    """
    from backend.trading.domain import ExecutionReport, OrderStatus, Venue
    from backend.trading.ledger import upsert_order_projection

    with factory() as session:
        upsert_order_projection(
            session,
            ExecutionReport(
                client_order_id="projection-dump-probe",
                venue=Venue.POLYMARKET_PAPER,
                status=OrderStatus.FILLED,
                broker_order_id="polymarket-paper-000001",
                filled_quantity=Decimal("89.285714"),
                filled_notional=Decimal("49.99999984"),
                average_fill_price=Decimal("0.56"),
                occurred_at=datetime.now(timezone.utc),
                metadata={"api_key": "METADATASENTINELVALUE", "note": "NESTEDSENTINEL"},
            ),
        )
        session.commit()
        # The sentinel really is in the column, or this test is vacuous again.
        stored = session.query(UnifiedOrder).one()
        assert "METADATASENTINELVALUE" in json.dumps(stored.order_metadata)

    response = client.get(f"{TRADING_PREFIX}/orders")

    assert response.json()[0]["client_order_id"] == "projection-dump-probe"
    assert "METADATASENTINELVALUE" not in response.text
    assert "NESTEDSENTINEL" not in response.text
    # Field names, not free text: a rejection reason mentioning metadata is not
    # a dump, and asserting on the whole body made this fire on benign content.
    assert not any("metadata" in key for key in response.json()[0])


def test_events_return_the_sanitized_audit_chain(client, factory, paper_mode):
    with factory() as session:
        route_one_real_order(session)

    body = client.get(f"{TRADING_PREFIX}/events").json()

    types = [event["event_type"] for event in body]
    assert types == [
        "proposal_created",
        "risk_approved",
        "order_submitted",
        "order_acknowledged",
        "order_filled",
    ]
    assert all(isinstance(event["sequence"], int) for event in body)


def test_events_return_only_allowlisted_payload_keys(client, factory, paper_mode):
    """The allowlist is the only control over what ledger payload content
    reaches an unauthenticated response, and TradingEventResponse.payload is
    typed dict[str, Any], so response_model provides no backstop.

    The row is written DIRECTLY rather than through the service, on purpose.
    Planting a sentinel on proposal.rationale or proposal.metadata proves
    nothing: the service overwrites metadata with a hard-coded literal and no
    payload builder ever emits rationale, so the sentinel cannot reach the
    column, cannot reach the response, and the assertion cannot fail for any
    implementation of the handler. Deleting the allowlist left the whole suite
    green. This test writes the hostile payload where the filter will actually
    see it.
    """
    with factory() as session:
        session.add(
            TradingEvent(
                event_id="payload-filter-probe",
                aggregate_id="payload-filter-probe",
                sequence=1,
                event_type="proposal_created",
                occurred_at=datetime.now(timezone.utc),
                payload={
                    "proposal_id": "payload-filter-probe",  # allowlisted, must survive
                    "rationale": "RATIONALESENTINEL api_key=sk-live-XYZ",
                    "identity": "IDENTITYSENTINEL",
                    "api_key": "PAYLOADKEYSENTINEL",
                    "caller_metadata": {"secret": "NESTEDPAYLOADSENTINEL"},
                    # The subset leg only catches a widening whose new key is
                    # present here, so plant the keys a real widening would most
                    # plausibly add. These four are adapter- or caller-controlled
                    # free text that real ledger writers do emit, which is
                    # precisely why they are excluded.
                    "client_order_id": "CLIENTORDERSENTINEL",
                    "broker_order_id": "BROKERORDERSENTINEL",
                    "metadata": {"secret": "METADATAKEYSENTINEL"},
                    "context": "CONTEXTSENTINEL",
                },
                previous_hash="0" * 64,
                event_hash="1" * 64,
            )
        )
        session.commit()

    response = client.get(f"{TRADING_PREFIX}/events")
    body = response.json()

    assert len(body) == 1
    returned = set(body[0]["payload"])
    # Pinned literally, not read from the constant under test: comparing the
    # response against main._TRADING_EVENT_PAYLOAD_KEYS would pass for any
    # widening of that set, which is the erosion this leg exists to catch.
    assert returned <= {"proposal_id"}, sorted(returned - {"proposal_id"})
    # ...and it must not be filtering everything away.
    assert body[0]["payload"]["proposal_id"] == "payload-filter-probe"

    for sentinel in (
        "RATIONALESENTINEL",
        "sk-live-XYZ",
        "IDENTITYSENTINEL",
        "PAYLOADKEYSENTINEL",
        "NESTEDPAYLOADSENTINEL",
        "CLIENTORDERSENTINEL",
        "BROKERORDERSENTINEL",
        "METADATAKEYSENTINEL",
        "CONTEXTSENTINEL",
    ):
        assert sentinel not in response.text


def test_listing_endpoints_bound_their_limit(client, paper_mode):
    for name in ("orders", "events"):
        assert client.get(f"{TRADING_PREFIX}/{name}", params={"limit": 10**9}).status_code == 422
        assert client.get(f"{TRADING_PREFIX}/{name}", params={"limit": 0}).status_code == 422


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


def test_portfolio_reports_unavailable_rather_than_inventing_state(
    client, paper_mode
):
    """weather_portfolio_state returns None rather than a placeholder when it
    cannot read real state. The API must carry that through, not paper over it
    with an adapter snapshot -- both production adapters return a hard-coded
    10000.00 that looks like an account read and is not one."""
    body = client.get(f"{TRADING_PREFIX}/portfolio").json()

    assert body["available"] is False
    assert body["equity"] is None
    assert body["cash"] is None
    assert body["positions"] == []


# ---------------------------------------------------------------------------
# The manual paper run
# ---------------------------------------------------------------------------


def test_a_run_that_proposes_nothing_is_a_success(client, paper_mode):
    response = client.post(f"{TRADING_PREFIX}/paper/run")

    assert response.status_code == 200
    body = response.json()
    assert body["ran"] is True
    assert body["proposals"] == 0
    assert body["results"] == []


def test_the_run_refuses_when_the_kill_switch_is_engaged(
    client, paper_mode, monkeypatch, factory
):
    """The status field and the refusal must read the SAME flag.

    Asserting only one of the two is how a reported control and an enforced one
    drift apart.
    """
    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)

    assert client.get(f"{TRADING_PREFIX}/status").json()["kill_switch"]["engaged"] is True

    response = client.post(f"{TRADING_PREFIX}/paper/run")
    assert response.status_code == 409
    assert response.json()["refused"] == "kill_switch_engaged"

    with factory() as session:
        assert session.query(TradingEvent).count() == 0
        assert session.query(UnifiedOrder).count() == 0


def test_the_run_refuses_outside_paper_mode(client, monkeypatch, factory):
    """The startup guard is a snapshot and does not protect handlers.

    Verified: a bare TestClient does not run lifespan, so a route with no guard
    of its own answers 200 with EXECUTION_MODE='live'. The guard has to be in
    the handler.
    """
    monkeypatch.setattr(settings, "EXECUTION_MODE", "live")

    response = client.post(f"{TRADING_PREFIX}/paper/run")

    assert response.status_code == 409
    assert response.json()["refused"] == "not_paper_mode"
    with factory() as session:
        assert session.query(TradingEvent).count() == 0


def test_a_failing_run_reports_nothing_and_leaves_nothing(
    client, paper_mode, monkeypatch, factory
):
    """No partial results, no durable rows.

    Reporting outcomes accumulated before a failure would tell the caller orders
    exist that do not -- the producer-reports-its-own-intent failure, at the HTTP
    boundary.
    """
    from backend.core import scheduler as scheduler_module

    def explode(*args, **kwargs):
        raise RuntimeError("storage refused")

    monkeypatch.setattr(scheduler_module, "run_manual_paper_lane", explode)

    response = client.post(f"{TRADING_PREFIX}/paper/run")

    assert response.status_code == 503
    body = response.json()
    assert body["refused"] == "run_failed"
    assert "results" not in body or body["results"] == []
    assert "storage refused" not in response.text

    with factory() as session:
        assert session.query(TradingEvent).count() == 0
        assert session.query(UnifiedOrder).count() == 0


def test_the_run_is_not_reentrant(paper_mode, factory, monkeypatch):
    """Forced overlap, not an accident of synchronous bodies.

    The lane body contains no awaits today, so two handlers cannot interleave by
    accident -- which makes a naive concurrency test pass for a reason that
    disappears the day a real market-data client is wired. This drives the
    handler coroutines directly and holds the first one open until the second
    has been answered, so the overlap is real. TestClient cannot do it: it
    serializes every request through a single portal.
    """
    import asyncio

    from backend.core import scheduler as scheduler_module

    async def drive():
        # A lock bound to this test's loop, so the assertion is about the guard
        # rather than about loop reuse across tests.
        monkeypatch.setattr(main, "_paper_run_lock", asyncio.Lock())
        holding = asyncio.Event()
        release = asyncio.Event()

        async def slow_run(db):
            holding.set()
            await release.wait()
            return scheduler_module.PaperLaneOutcome(0, ())

        monkeypatch.setattr(main, "_run_manual_paper_lane_async", slow_run)

        first_session, second_session = factory(), factory()
        try:
            first = asyncio.create_task(main.run_paper_lane(db=first_session))
            await asyncio.wait_for(holding.wait(), timeout=5)

            second = await main.run_paper_lane(db=second_session)

            release.set()
            first_result = await asyncio.wait_for(first, timeout=5)
            return first_result, second
        finally:
            first_session.close()
            second_session.close()

    first_result, second = asyncio.run(drive())

    assert second.status_code == 409
    assert json.loads(second.body)["refused"] == "run_in_progress"
    # The first caller still succeeded; the guard refuses the newcomer, it does
    # not break the run already in flight.
    assert first_result.ran is True


def test_the_run_route_commits_what_the_lane_wrote(
    client, factory, paper_mode, monkeypatch
):
    """The route owns the transaction, so prove it takes it.

    get_db neither commits nor rolls back and the execution service is forbidden
    from doing either, so if this handler forgets, every row the lane wrote is
    discarded -- which is exactly the bug the scheduler job shipped with. The
    read-back deliberately uses a session the request never touched: a shared
    session would find the uncommitted row in the writer's own identity map and
    prove nothing.
    """
    from backend.core import scheduler as scheduler_module

    async def writing_run(db):
        db.add(
            TradingEvent(
                event_id="durability-probe",
                aggregate_id="durability-probe",
                sequence=1,
                event_type="proposal_created",
                occurred_at=datetime.now(timezone.utc),
                payload={"proposal_id": "durability-probe"},
                previous_hash="0" * 64,
                event_hash="1" * 64,
            )
        )
        db.flush()
        return scheduler_module.PaperLaneOutcome(0, ())

    monkeypatch.setattr(main, "_run_manual_paper_lane_async", writing_run)

    assert client.post(f"{TRADING_PREFIX}/paper/run").status_code == 200

    with factory() as verifier:
        assert verifier.query(TradingEvent).count() == 1


def test_orders_carry_the_instrument_identity(client, factory, paper_mode):
    """An order row that cannot name its instrument is not auditable.

    unified_orders is keyed by client_order_id and the event log by
    proposal_id, so before these columns existed nothing connected a filled
    order to the symbol and direction it was placed for.
    """
    with factory() as session:
        route_one_real_order(session)

    order = client.get(f"{TRADING_PREFIX}/orders").json()[0]

    assert order["symbol"], "the order does not say which instrument it was for"
    assert order["side"] in ("buy", "sell")
    assert order["asset_class"] == "prediction_weather"
    assert order["proposal_id"], "the order cannot be joined to its audit events"


def test_order_identity_is_not_sourced_from_adapter_metadata(client, factory, paper_mode):
    """The identity columns must come from the typed order, not report metadata."""
    with factory() as session:
        route_one_real_order(
            session, metadata={"symbol": "METADATA_SYMBOL_SENTINEL"}
        )

    body = client.get(f"{TRADING_PREFIX}/orders").text

    assert "METADATA_SYMBOL_SENTINEL" not in body


def test_status_lists_the_alpaca_venue_so_its_states_are_reachable(
    client, paper_mode, monkeypatch
):
    """The dashboard distinguishes Alpaca disconnected/configured/connected.

    "Connected" requires the venue to appear in status.venues with
    execution_enabled. _venue_states() returned only the two prediction venues,
    so that state was unreachable from any real response and the panel test that
    asserted it did so against a hand-built fixture the API cannot produce.
    """
    monkeypatch.setattr(settings, "STOCK_CRYPTO_LANE_ENABLED", True)

    venues = {v["venue"]: v for v in client.get(f"{TRADING_PREFIX}/status").json()["venues"]}

    assert "alpaca_paper" in venues, "the Alpaca venue is absent from status"
    assert venues["alpaca_paper"]["execution_enabled"] is True
    assert venues["alpaca_paper"]["simulation"] is False


def test_the_alpaca_venue_reports_monitor_only_when_the_lane_is_off(
    client, paper_mode, monkeypatch
):
    monkeypatch.setattr(settings, "STOCK_CRYPTO_LANE_ENABLED", False)

    venues = {v["venue"]: v for v in client.get(f"{TRADING_PREFIX}/status").json()["venues"]}

    assert venues["alpaca_paper"]["execution_enabled"] is False
    assert venues["alpaca_paper"]["monitor_only"] is True
