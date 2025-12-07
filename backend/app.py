import csv
import datetime as dt
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


DATABASE_URL = "sqlite:///./data.db"
FILES_DIR = Path(__file__).resolve().parent.parent / "files"
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXCEL_EPOCH = dt.date(1899, 12, 30)
IMAGE_DIR = FILES_DIR / "image"
SW_PATH = STATIC_DIR / "service-worker.js"

engine = create_engine(
    DATABASE_URL, echo=False, future=True, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def excel_serial_to_date(value: float) -> dt.date:
    return EXCEL_EPOCH + dt.timedelta(days=int(value))

def _ts(entry_ts: Optional[dt.datetime]) -> dt.datetime:
    if entry_ts is None:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    if entry_ts.tzinfo is None:
        return entry_ts.replace(tzinfo=dt.timezone.utc)
    return entry_ts


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "y", "yes", "t", "on"}


def parse_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return default


def parse_date_value(value: Optional[str]) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
        if numeric.is_integer() and numeric >= 30000:
            return excel_serial_to_date(numeric)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    for fmt in ("%Y년 %m월 %d일",):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def column_index_from_ref(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return index


def load_xlsx_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        return []
    with zipfile.ZipFile(path) as z:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(
                ".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"
            ):
                texts = [
                    t.text or ""
                    for t in si.findall(
                        ".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                    )
                ]
                shared_strings.append("".join(texts))

        rows: List[List[str]] = []
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with z.open("xl/worksheets/sheet1.xml") as f:
            root = ET.parse(f).getroot()
            for row in root.findall(".//a:sheetData/a:row", ns):
                cells: Dict[int, str] = {}
                max_idx = 0
                for cell in row.findall("a:c", ns):
                    ref = cell.attrib.get("r", "")
                    col_idx = column_index_from_ref(ref)
                    t_attr = cell.attrib.get("t")
                    raw = ""
                    if t_attr == "s":
                        v_elem = cell.find("a:v", ns)
                        raw = shared_strings[int(v_elem.text)] if v_elem is not None else ""
                    elif t_attr == "inlineStr":
                        t_elem = cell.find(".//a:t", ns)
                        raw = t_elem.text if t_elem is not None else ""
                    else:
                        v_elem = cell.find("a:v", ns)
                        raw = v_elem.text if v_elem is not None else ""
                    if col_idx:
                        cells[col_idx] = raw
                        max_idx = max(max_idx, col_idx)
                if max_idx == 0:
                    rows.append([])
                    continue
                ordered = [cells.get(i, "") for i in range(1, max_idx + 1)]
                rows.append(ordered)
        return rows


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for row in reader:
            cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if any(cleaned.values()):
                rows.append(cleaned)
    return rows


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    stop_play = Column(Boolean, default=False, nullable=False)
    uid = Column(String, nullable=True)
    coupon_url = Column(String, nullable=True)

    characters = relationship(
        "Character", back_populates="game", cascade="all, delete-orphan"
    )
    currencies = relationship(
        "Currency", back_populates="game", cascade="all, delete-orphan"
    )
    events = relationship(
        "GameEvent", back_populates="game", cascade="all, delete-orphan"
    )
    spendings = relationship(
        "Spending", back_populates="game", cascade="all, delete-orphan"
    )

    @property
    def during_play(self) -> bool:
        return self.end_date is None

    @property
    def playtime_days(self) -> int:
        days = (dt.date.today() - self.start_date).days + 1
        return max(days, 0)

    @property
    def playtime_label(self) -> str:
        return f"{self.playtime_days}일"


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    level = Column(Integer, nullable=True)
    grade = Column(String, nullable=True)
    overpower = Column(Integer, nullable=True, default=0)
    position = Column(String, nullable=True)
    memo = Column(String, nullable=True)
    is_have = Column(Boolean, default=True, nullable=False)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)

    game = relationship("Game", back_populates="characters")


class Currency(Base):
    __tablename__ = "currencies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    counts = Column(Integer, default=0, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=func.now())
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)

    game = relationship("Game", back_populates="currencies")


class GameEvent(Base):
    __tablename__ = "game_events"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    type = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    priority = Column(String, nullable=False)

    game = relationship("Game", back_populates="events")

    @property
    def state(self) -> str:
        today = dt.date.today()
        if self.start_date and today < self.start_date:
            return "예정"
        if self.end_date and today > self.end_date:
            return "종료"
        return "진행 중"


class Spending(Base):
    __tablename__ = "spendings"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    paying = Column(String, nullable=False)
    paying_date = Column(Date, nullable=False)
    type = Column(String, nullable=False)
    expiration_days = Column(Integer, default=0, nullable=False)

    game = relationship("Game", back_populates="spendings")

    @property
    def next_paying_date(self) -> dt.date:
        return self.paying_date + dt.timedelta(days=self.expiration_days)

    @property
    def remain_date(self) -> int:
        return (self.next_paying_date - dt.date.today()).days

    @property
    def is_repaying(self) -> str:
        days = self.remain_date
        if days <= 3:
            return "갱신필요"
        if days <= 7:
            return "유의"
        if days <= 15:
            return "여유"
        return "여유"


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    gift_code = Column(String, nullable=True)
    state = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    events = relationship(
        "ClickEvent", back_populates="item", cascade="all, delete-orphan"
    )


class ClickEvent(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    before_state = Column(String, nullable=True)
    after_state = Column(String, nullable=True)
    gift_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    item = relationship("Item", back_populates="events")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_columns()


def ensure_columns() -> None:
    with engine.begin() as conn:
        cols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(games)").all()
        }
        if "uid" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN uid STRING")
        if "coupon_url" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN coupon_url STRING")
        ccols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(currencies)").all()
        }
        if "timestamp" not in ccols:
            conn.exec_driver_sql(
                "ALTER TABLE currencies ADD COLUMN timestamp DATETIME"
            )


def seed_games(db: Session) -> Dict[str, Game]:
    path = FILES_DIR / "GameDB.xlsx"
    rows = load_xlsx_rows(path)
    if not rows:
        return {}
    headers = rows[0]
    header_len = len(headers)
    games: Dict[str, Game] = {}
    for raw_row in rows[1:]:
        padded = (raw_row + [""] * (header_len - len(raw_row)))[:header_len]
        row = dict(zip(headers, padded))
        title = row.get("Title")
        if not title:
            continue
        start_date = parse_date_value(row.get("StartDate"))
        end_date = parse_date_value(row.get("EndDate"))
        stop_play = parse_bool(row.get("StopPlay"), default=False)
        uid = row.get("UID") or None
        coupon_url = row.get("CouponURL") or None
        if not start_date:
            continue
        if end_date:
            stop_play = True
        game = db.execute(select(Game).where(Game.title == title)).scalar_one_or_none()
        if not game:
            game = Game(
                title=title, start_date=start_date, end_date=end_date, stop_play=stop_play
            )
            db.add(game)
        else:
            game.start_date = start_date
            game.end_date = end_date
            game.stop_play = stop_play
        game.uid = uid
        game.coupon_url = coupon_url
        games[title] = game
    db.flush()
    return games


def seed_characters(db: Session, games: Dict[str, Game]) -> None:
    rows = read_csv_rows(FILES_DIR / "CharacterDB.csv")
    for row in rows:
        title = row.get("Title")
        game_title = row.get("GameDB")
        if not title or not game_title:
            continue
        game = games.get(game_title)
        if not game:
            continue
        character = db.execute(
            select(Character).where(
                Character.title == title, Character.game_id == game.id
            )
        ).scalar_one_or_none()
        if not character:
            character = Character(title=title, game=game)
            db.add(character)
        character.level = parse_int(row.get("Level"))
        character.grade = row.get("Grade") or None
        character.overpower = parse_int(row.get("Overpower"), default=0) or 0
        character.position = row.get("Position") or None
        character.memo = row.get("Memo") or None
        character.is_have = parse_bool(row.get("isHave"), default=True)
    db.flush()


def seed_currencies(db: Session, games: Dict[str, Game]) -> None:
    rows = read_csv_rows(FILES_DIR / "CurrencyDB.csv")
    for row in rows:
        title = row.get("Title")
        game_title = row.get("GameDB")
        if not title or not game_title:
            continue
        game = games.get(game_title)
        if not game:
            continue
        counts = parse_int(row.get("Counts"), default=0) or 0
        ts_date = parse_date_value(row.get("lateDate")) or dt.date.today()
        ts = dt.datetime.combine(ts_date, dt.time.min, dt.timezone.utc)
        entry = Currency(title=title, game=game, counts=counts, timestamp=ts)
        db.add(entry)
    db.flush()


def seed_game_events(db: Session, games: Dict[str, Game]) -> None:
    rows = read_csv_rows(FILES_DIR / "EventDB.csv")
    for row in rows:
        title = row.get("Title")
        game_title = row.get("GameDB")
        if not title or not game_title:
            continue
        game = games.get(game_title)
        if not game:
            continue
        start_date = parse_date_value(row.get("StartDate")) or dt.date.today()
        end_date = parse_date_value(row.get("EndDate"))
        evt_type = row.get("Type") or ""
        priority = row.get("Priority") or ""
        event = (
            db.execute(
                select(GameEvent)
                .where(GameEvent.title == title, GameEvent.game_id == game.id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not event:
            event = GameEvent(title=title, game=game)
            db.add(event)
        event.type = evt_type
        event.start_date = start_date
        event.end_date = end_date
        event.priority = priority
    db.flush()


def seed_spendings(db: Session, games: Dict[str, Game]) -> None:
    rows = read_csv_rows(FILES_DIR / "SpendingDB.csv")
    for row in rows:
        title = row.get("Title")
        game_title = row.get("GameDB")
        if not title or not game_title:
            continue
        game = games.get(game_title)
        if not game:
            continue
        paying_date = parse_date_value(row.get("PayingDate")) or dt.date.today()
        expiration_days = parse_int(row.get("ExpirationDate"), default=0) or 0
        spending = db.execute(
            select(Spending).where(
                Spending.title == title, Spending.game_id == game.id
            )
        ).scalar_one_or_none()
        if not spending:
            spending = Spending(title=title, game=game)
            db.add(spending)
        spending.paying = row.get("Paying") or ""
        spending.type = row.get("Type") or ""
        spending.paying_date = paying_date
        spending.expiration_days = expiration_days
    db.flush()


def seed_data_from_files() -> None:
    if not FILES_DIR.exists():
        return
    db = SessionLocal()
    try:
        games = seed_games(db)
        if games:
            seed_characters(db, games)
            seed_currencies(db, games)
            seed_game_events(db, games)
            seed_spendings(db, games)
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ItemCreate(BaseModel):
    label: str = Field(..., examples=["Gift A"])
    gift_code: Optional[str] = Field(None, examples=["ABC123"])
    state: str = Field("pending", examples=["pending"])


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    gift_code: Optional[str] = None
    state: str
    created_at: dt.datetime
    updated_at: dt.datetime


class ActionPayload(BaseModel):
    item_id: int
    action: str = Field(..., examples=["mark_done"])
    next_state: Optional[str] = Field(None, description="State to set after action")
    gift_code: Optional[str] = Field(None, description="Gift code to store/update")


class WeeklyBucket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt.date
    count: int


class WeeklyMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    buckets: List[WeeklyBucket]
    from_date: dt.date
    to_date: dt.date


class CurrencyTimeseriesBucket(BaseModel):
    date: dt.date
    count: int


class CurrencyTimeseries(BaseModel):
    title: str
    buckets: List[CurrencyTimeseriesBucket]
    from_date: dt.date
    to_date: dt.date


class GameOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start_date: dt.date
    end_date: Optional[dt.date]
    playtime_days: int
    playtime_label: str
    during_play: bool
    stop_play: bool
    uid: Optional[str]
    coupon_url: Optional[str]

    @field_validator("uid", mode="before")
    def coerce_uid(cls, v):
        if v is None:
            return None
        return str(v)

    @field_serializer("uid")
    def serialize_uid(self, value):
        return str(value) if value is not None else None


class CharacterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    level: Optional[int]
    grade: Optional[str]
    overpower: Optional[int]
    position: Optional[str]
    memo: Optional[str]
    is_have: bool
    game_id: int


class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    counts: int
    timestamp: dt.datetime
    game_id: int


class GameEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    title: str
    type: str
    start_date: dt.date
    end_date: Optional[dt.date]
    priority: str
    state: str


class SpendingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    title: str
    paying: str
    paying_date: dt.date
    type: str
    expiration_days: int
    next_paying_date: dt.date
    remain_date: int
    is_repaying: str


class CurrencyAdjust(BaseModel):
    counts: int = Field(..., description="설정할 재화 수량 (증감이 아닌 절댓값)")


class SpendingAdjust(BaseModel):
    paying_date: Optional[dt.date] = Field(
        None, description="다시 결제한 날짜(미입력 시 오늘)"
    )
    expiration_days: Optional[int] = Field(
        None, description="유효 일수(미입력 시 기존 유지)"
    )
    paying: Optional[str] = Field(None, description="결제 금액 텍스트(옵션)")


class EventCreate(BaseModel):
    title: str
    type: str
    start_date: dt.date
    end_date: Optional[dt.date] = None
    priority: str

    @field_validator("end_date", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        if v in ("", None):
            return None
        return v


class CharacterUpdate(BaseModel):
    level: Optional[int] = None
    grade: Optional[str] = None
    overpower: Optional[int] = None
    is_have: Optional[bool] = None


class GameEndPayload(BaseModel):
    end_date: Optional[dt.date] = Field(
        None, description="종료일(미입력 시 오늘 날짜로 종료)"
    )


app = FastAPI(title="Dashboard Backend", version="0.2.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if IMAGE_DIR.exists():
    app.mount("/assets", StaticFiles(directory=IMAGE_DIR), name="assets")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    if not SW_PATH.exists():
        raise HTTPException(status_code=404)
    return FileResponse(SW_PATH, media_type="application/javascript")

@app.on_event("startup")
def on_startup():
    init_db()
    seed_data_from_files()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, db: Session = Depends(get_db)):
    item = Item(label=payload.label, gift_code=payload.gift_code, state=payload.state)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/items", response_model=List[ItemOut])
def list_items(db: Session = Depends(get_db)):
    result = db.execute(select(Item).order_by(Item.id.asc()))
    return result.scalars().all()


@app.post("/actions/click", response_model=ItemOut)
def click_action(payload: ActionPayload, db: Session = Depends(get_db)):
    item = db.get(Item, payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    before_state = item.state
    if payload.next_state:
        item.state = payload.next_state
    if payload.gift_code:
        item.gift_code = payload.gift_code

    event = ClickEvent(
        item=item,
        action=payload.action,
        before_state=before_state,
        after_state=item.state,
        gift_code=item.gift_code,
    )
    db.add(event)
    db.commit()
    db.refresh(item)
    return item


@app.get("/metrics/weekly", response_model=WeeklyMetrics)
def weekly_metrics(db: Session = Depends(get_db)):
    today = dt.date.today()
    start_date = today - dt.timedelta(days=6)
    start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)

    bucket_query = (
        select(func.date(ClickEvent.created_at).label("d"), func.count(ClickEvent.id))
        .where(ClickEvent.created_at >= start_dt)
        .group_by("d")
    )
    rows = db.execute(bucket_query).all()
    counts_by_date = {dt.date.fromisoformat(row[0]): row[1] for row in rows}

    buckets: List[WeeklyBucket] = []
    for i in range(7):
        day = start_date + dt.timedelta(days=i)
        buckets.append(WeeklyBucket(date=day, count=counts_by_date.get(day, 0)))

    return WeeklyMetrics(buckets=buckets, from_date=start_date, to_date=today)


@app.get("/games", response_model=List[GameOut])
def list_games(
    during_play_only: bool = False,
    include_stopped: bool = False,
    db: Session = Depends(get_db),
) -> List[Game]:
    query = select(Game)
    if not include_stopped:
        query = query.where(Game.stop_play.is_(False))
    if during_play_only:
        query = query.where(Game.end_date.is_(None))
    result = db.execute(query)
    games = result.scalars().all()
    games.sort(key=lambda g: g.playtime_days, reverse=True)
    return games


def get_game_or_404(game_id: int, db: Session) -> Game:
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@app.get("/games/{game_id}/characters", response_model=List[CharacterOut])
def list_characters(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    result = db.execute(
        select(Character)
        .where(Character.game_id == game.id)
        .order_by(Character.is_have.desc(), Character.title.asc())
    )
    return result.scalars().all()


@app.get("/games/{game_id}/currencies", response_model=List[CurrencyOut])
def list_currencies(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    rows = (
        db.execute(
            select(Currency)
            .where(Currency.game_id == game.id)
            .order_by(Currency.title.asc(), Currency.timestamp.desc(), Currency.id.desc())
        )
        .scalars()
        .all()
    )
    latest_by_title = {}
    for r in rows:
        if r.title not in latest_by_title:
            latest_by_title[r.title] = r
    return list(latest_by_title.values())


@app.post("/currencies/{currency_id}/adjust", response_model=CurrencyOut)
def adjust_currency(
    currency_id: int, payload: CurrencyAdjust, db: Session = Depends(get_db)
):
    currency = db.get(Currency, currency_id)
    if not currency:
        raise HTTPException(status_code=404, detail="Currency not found")
    new_entry = Currency(
        title=currency.title,
        game=currency.game,
        counts=payload.counts,
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry


@app.get("/games/{game_id}/events", response_model=List[GameEventOut])
def list_game_events(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    result = db.execute(
        select(GameEvent)
        .where(GameEvent.game_id == game.id)
        .order_by(GameEvent.start_date.asc(), GameEvent.id.asc())
    )
    return result.scalars().all()


@app.get("/games/{game_id}/spendings", response_model=List[SpendingOut])
def list_spendings(game_id: int, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    result = db.execute(
        select(Spending)
        .where(Spending.game_id == game.id)
    )
    spendings = result.scalars().all()
    spendings.sort(key=lambda s: s.next_paying_date)
    return spendings


@app.post("/games/{game_id}/end", response_model=GameOut)
def end_game(game_id: int, payload: GameEndPayload, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    game.end_date = payload.end_date or dt.date.today()
    game.stop_play = True
    db.commit()
    db.refresh(game)
    return game


@app.post("/spendings/{spending_id}/renew", response_model=SpendingOut)
def renew_spending(
    spending_id: int, payload: SpendingAdjust, db: Session = Depends(get_db)
):
    spending = db.get(Spending, spending_id)
    if not spending:
        raise HTTPException(status_code=404, detail="Spending not found")
    if payload.paying_date:
        spending.paying_date = payload.paying_date
    else:
        spending.paying_date = dt.date.today()
    if payload.expiration_days is not None:
        spending.expiration_days = payload.expiration_days
    if payload.paying is not None:
        spending.paying = payload.paying
    db.commit()
    db.refresh(spending)
    return spending


@app.post("/games/{game_id}/events", response_model=GameEventOut, status_code=201)
def create_game_event(
    game_id: int, payload: EventCreate, db: Session = Depends(get_db)
):
    game = get_game_or_404(game_id, db)
    event = GameEvent(
        game=game,
        title=payload.title,
        type=payload.type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        priority=payload.priority,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.post("/characters/{character_id}/update", response_model=CharacterOut)
def update_character(
    character_id: int, payload: CharacterUpdate, db: Session = Depends(get_db)
):
    character = db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    if payload.level is not None:
        character.level = payload.level
    if payload.grade is not None:
        character.grade = payload.grade
    if payload.overpower is not None:
        character.overpower = payload.overpower
    if payload.is_have is not None:
        character.is_have = payload.is_have
    db.commit()
    db.refresh(character)
    return character


def _latest_count_on_or_before(entries: List[Currency], target: dt.date, title: Optional[str] = None) -> int:
    day_end = dt.datetime.combine(target, dt.time.max, dt.timezone.utc)
    filtered = [
        e
        for e in entries
        if (title is None or e.title == title) and _ts(e.timestamp) <= day_end
    ]
    if not filtered:
        return 0
    filtered.sort(key=lambda e: (_ts(e.timestamp), e.id), reverse=True)
    if title:
        return filtered[0].counts
    # sum latest per title
    latest_by_title: dict[str, Currency] = {}
    for e in filtered:
        if e.title not in latest_by_title:
            latest_by_title[e.title] = e
    return sum(v.counts for v in latest_by_title.values())


def _max_or_latest_in_range(
    entries: List[Currency],
    start_date: dt.date,
    end_date: dt.date,
    title: Optional[str] = None,
) -> int:
    start_dt = dt.datetime.combine(start_date, dt.time.min, dt.timezone.utc)
    end_dt = dt.datetime.combine(end_date, dt.time.max, dt.timezone.utc)
    if title:
        in_range = [
            e
            for e in entries
            if e.title == title and start_dt <= _ts(e.timestamp) <= end_dt
        ]
        if in_range:
            return max(e.counts for e in in_range)
        return _latest_count_on_or_before(entries, end_date, title=title)

    # ALL: sum per title using their own max-or-latest in range
    titles = {e.title for e in entries}
    total = 0
    for t in titles:
        total += _max_or_latest_in_range(entries, start_date, end_date, title=t)
    return total


@app.get("/games/{game_id}/currencies/timeseries", response_model=CurrencyTimeseries)
def currency_timeseries(
    game_id: int,
    title: Optional[str] = None,
    days: int = 7,
    weekly: bool = False,
    weeks: int = 8,
    db: Session = Depends(get_db),
):
    game = get_game_or_404(game_id, db)
    entries = (
        db.execute(
            select(Currency)
            .where(Currency.game_id == game.id)
            .order_by(Currency.timestamp.asc(), Currency.id.asc())
        )
        .scalars()
        .all()
    )
    if weekly:
        weeks = max(1, min(weeks, 26))
        today = dt.date.today()
        delta = (today.weekday() + 1) % 7  # days since last Sunday
        current_week_start = today - dt.timedelta(days=delta)
        buckets: List[CurrencyTimeseriesBucket] = []
        for i in range(weeks):
            week_start = current_week_start - dt.timedelta(days=7 * i)
            week_end = week_start + dt.timedelta(days=6)
            count = _max_or_latest_in_range(entries, week_start, week_end, title=title)
            buckets.append(CurrencyTimeseriesBucket(date=week_end, count=count))
        return CurrencyTimeseries(
            title=title or "ALL",
            buckets=buckets,
            from_date=buckets[-1].date,
            to_date=buckets[0].date,
        )

    days = max(1, min(days, 30))
    today = dt.date.today()
    start = today - dt.timedelta(days=days - 1)
    buckets: List[CurrencyTimeseriesBucket] = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        count = _latest_count_on_or_before(entries, day, title=title)
        buckets.append(CurrencyTimeseriesBucket(date=day, count=count))
    return CurrencyTimeseries(
        title=title or "ALL", buckets=buckets, from_date=start, to_date=today
    )


@app.get("/", include_in_schema=False)
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Frontend not built yet"}
