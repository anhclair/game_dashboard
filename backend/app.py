import csv
import json
import os
import datetime as dt
import time
import threading
from collections import deque
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")
FILES_DIR = Path(__file__).resolve().parent.parent / "files"
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXCEL_EPOCH = dt.date(1899, 12, 30)
IMAGE_DIR = FILES_DIR / "image"
SW_PATH = STATIC_DIR / "service-worker.js"
LOCAL_TZ = dt.timezone(dt.timedelta(hours=9))  # KST
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "10"))
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "120"))
RATE_LIMIT_MUTATION_MAX = int(os.getenv("RATE_LIMIT_MUTATION_MAX", "40"))
EVENT_TYPE_OPTIONS = {"업데이트", "스토리", "픽업", "컨텐츠", "파밍", "시즌", "주년", "페이백"}
EVENT_PRIORITY_OPTIONS = {"매우낮음", "낮음", "중간", "높음", "매우높음"}

REFRESH_DEFAULTS: Dict[str, Tuple[Optional[int], Optional[str]]] = {
    "니케": (3, "05:00"),
    "헤이즈 리버브": (2, "05:00"),
    "던파 모바일": (5, "06:00"),
    "림버스 컴퍼니": (5, "06:00"),
    "브라운더스트 2": (5, "09:00"),
    "소녀전선2 망명": (2, "05:00"),
    "명일방주": (2, "04:00"),
    "스텔라 소라": (2, "05:00"),
}

engine = create_engine(
    DATABASE_URL, echo=False, future=True, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def excel_serial_to_date(value: float) -> dt.date:
    return EXCEL_EPOCH + dt.timedelta(days=int(value))

def today_local() -> dt.date:
    return dt.datetime.now(LOCAL_TZ).date()

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

def parse_float(value: Optional[str], default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return default


def normalize_currency_type(value: Optional[str]) -> str:
    text = (value or "NONE").strip().strip("`'\"")
    up = text.upper()
    if up in {"MAIN", "GACHA", "NONE"}:
        return up
    return "NONE"


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


def parse_time_value(value: Optional[str]) -> Optional[dt.time]:
    if value is None:
        return None
    if isinstance(value, dt.time):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None


def parse_refresh_day(value: Optional[str]) -> Optional[int]:
    day = parse_int(value)
    if day is None:
        return None
    if 1 <= day <= 7:
        return day
    return None


WEEKDAY_LABELS = {
    1: "일요일",
    2: "월요일",
    3: "화요일",
    4: "수요일",
    5: "목요일",
    6: "금요일",
    7: "토요일",
}


def weekday_label(day: Optional[int]) -> Optional[str]:
    if day is None:
        return None
    return WEEKDAY_LABELS.get(day)


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


def load_game_gacha_map() -> Dict[str, int]:
    path = FILES_DIR / "GameDB.xlsx"
    rows = load_xlsx_rows(path)
    if not rows:
        return {}
    headers = rows[0]
    gacha_idx = headers.index("Gacha") if "Gacha" in headers else None
    title_idx = headers.index("Title") if "Title" in headers else None
    if gacha_idx is None or title_idx is None:
        return {}
    mapping: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) <= max(gacha_idx, title_idx):
            continue
        title = r[title_idx]
        gacha_val = parse_int(r[gacha_idx], default=0) or 0
        if not title:
            continue
        mapping[title] = gacha_val
    return mapping


def load_game_memo_map() -> Dict[str, str]:
    path = FILES_DIR / "GameDB.xlsx"
    rows = load_xlsx_rows(path)
    if not rows:
        return {}
    headers = rows[0]
    memo_idx = headers.index("Memo") if "Memo" in headers else None
    title_idx = headers.index("Title") if "Title" in headers else None
    if memo_idx is None or title_idx is None:
        return {}
    mapping: Dict[str, str] = {}
    for r in rows[1:]:
        if len(r) <= max(memo_idx, title_idx):
            continue
        title = r[title_idx]
        memo = r[memo_idx]
        if not title:
            continue
        if memo:
            mapping[title] = memo
    return mapping


def load_game_refresh_map() -> Dict[str, Tuple[Optional[int], Optional[dt.time]]]:
    path = FILES_DIR / "GameDB.xlsx"
    rows = load_xlsx_rows(path)
    if not rows:
        return {}
    headers = rows[0]
    title_idx = headers.index("Title") if "Title" in headers else None
    day_idx = headers.index("RefreshDay") if "RefreshDay" in headers else None
    time_idx = headers.index("RefreshTime") if "RefreshTime" in headers else None
    if title_idx is None or (day_idx is None and time_idx is None):
        return {}
    mapping: Dict[str, Tuple[Optional[int], Optional[dt.time]]] = {}
    for r in rows[1:]:
        if len(r) <= max(title_idx, day_idx or 0, time_idx or 0):
            continue
        title = r[title_idx]
        if not title:
            continue
        day_val = parse_refresh_day(r[day_idx]) if day_idx is not None else None
        time_val = parse_time_value(r[time_idx]) if time_idx is not None else None
        mapping[title] = (day_val, time_val)
    return mapping


def load_currency_meta_map() -> Dict[Tuple[str, str], Tuple[str, float]]:
    rows = read_csv_rows(FILES_DIR / "CurrencyDB.csv")
    mapping: Dict[Tuple[str, str], Tuple[str, float]] = {}
    for row in rows:
        title = row.get("Title")
        game_title = row.get("GameDB")
        if not title or not game_title:
            continue
        ctype = normalize_currency_type(row.get("Type"))
        value = parse_float(row.get("Value"), default=1.0) or 1.0
        mapping[(game_title, title)] = (ctype, value)
    return mapping


def parse_task_list(raw: Optional[str]) -> List[str]:
    if raw is None:
        return []
    return [part.strip() for part in str(raw).split(";") if part.strip()]


def encode_task_list(values: List[str]) -> str:
    return ";".join([v.strip() for v in values if v.strip()])


def decode_rewards(raw: Optional[str], length: int) -> List[List["RewardOut"]]:
    if not raw:
        return [[] for _ in range(length)]
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = []
    if not isinstance(data, list):
        data = []
    rewards: List[List[RewardOut]] = []
    for row in data:
        if not isinstance(row, list):
            rewards.append([])
            continue
        parsed_row: List[RewardOut] = []
        for item in row:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            count = parse_int(item.get("count"), default=0) or 0
            if title and count is not None:
                parsed_row.append(RewardOut(title=title, count=count))
        rewards.append(parsed_row)
    if len(rewards) < length:
        rewards.extend([[] for _ in range(length - len(rewards))])
    return rewards[:length]


def encode_rewards(rows: List[List["RewardIn"]]) -> str:
    serializable: List[List[Dict[str, object]]] = []
    for row in rows:
        serializable.append(
            [
                {"title": r.title.strip(), "count": int(r.count)}
                for r in row
                if r.title.strip()
            ]
        )
    return json.dumps(serializable, ensure_ascii=False)


def _decode_state(raw: Optional[str], length: int) -> List[bool]:
    if not raw:
        return [False] * length
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = []
    if not isinstance(data, list):
        data = []
    bools = [bool(x) for x in data][:length]
    if len(bools) < length:
        bools.extend([False] * (length - len(bools)))
    return bools


def _encode_state(values: List[bool]) -> str:
    return json.dumps([bool(v) for v in values])


def _spending_reward_mode(spending: "Spending") -> str:
    mode = (spending.reward_mode or "").upper()
    if mode in {"DAILY", "ONCE"}:
        return mode
    text = (spending.type or "").lower()
    if "패스" in text:
        return "ONCE"
    return "DAILY"


def _spending_rewards(spending: "Spending") -> List["RewardOut"]:
    return decode_reward_list(spending.reward_items)


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, unique=True, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    stop_play = Column(Boolean, default=False, nullable=False)
    uid = Column(String, nullable=True)
    coupon_url = Column(String, nullable=True)
    gacha = Column(Integer, nullable=True, default=0)
    memo = Column(String, nullable=True)
    refresh_day = Column(Integer, nullable=True)
    refresh_time = Column(String, nullable=True)

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
    tasks = relationship(
        "Task", back_populates="game", cascade="all, delete-orphan", uselist=False
    )

    @property
    def during_play(self) -> bool:
        return self.end_date is None

    @property
    def playtime_days(self) -> int:
        end_ref = self.end_date or dt.date.today()
        days = (end_ref - self.start_date).days
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
    type = Column(String, nullable=True)
    value = Column(Float, nullable=True)
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
    reward_mode = Column(String, nullable=True)
    reward_items = Column(String, nullable=True)
    last_reward_at = Column(DateTime(timezone=True), nullable=True)
    reward_once_granted = Column(Boolean, default=False, nullable=False)
    pass_current_level = Column(Integer, nullable=True)
    pass_max_level = Column(Integer, nullable=True)

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


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, unique=True)
    daily_tasks = Column(String, nullable=True)
    weekly_tasks = Column(String, nullable=True)
    monthly_tasks = Column(String, nullable=True)
    daily_rewards = Column(String, nullable=True)
    weekly_rewards = Column(String, nullable=True)
    monthly_rewards = Column(String, nullable=True)
    daily_reward_state = Column(String, nullable=True)
    weekly_reward_state = Column(String, nullable=True)
    monthly_reward_state = Column(String, nullable=True)
    daily_state = Column(String, nullable=True)
    weekly_state = Column(String, nullable=True)
    monthly_state = Column(String, nullable=True)
    last_daily_reset = Column(DateTime(timezone=True), nullable=True)
    last_weekly_reset = Column(DateTime(timezone=True), nullable=True)
    last_monthly_reset = Column(DateTime(timezone=True), nullable=True)

    game = relationship("Game", back_populates="tasks")
    histories = relationship(
        "TaskHistory", back_populates="task", cascade="all, delete-orphan"
    )


class TaskHistory(Base):
    __tablename__ = "task_histories"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    daily_done = Column(Integer, nullable=True)
    weekly_done = Column(Integer, nullable=True)
    monthly_done = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    task = relationship("Task", back_populates="histories")


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
        if "gacha" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN gacha INTEGER DEFAULT 0")
        if "memo" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN memo STRING")
        if "refresh_day" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN refresh_day INTEGER")
        if "refresh_time" not in cols:
            conn.exec_driver_sql("ALTER TABLE games ADD COLUMN refresh_time STRING")
        ccols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(currencies)").all()
        }
        if "timestamp" not in ccols:
            conn.exec_driver_sql(
                "ALTER TABLE currencies ADD COLUMN timestamp DATETIME"
            )
        if "type" not in ccols:
            conn.exec_driver_sql("ALTER TABLE currencies ADD COLUMN type STRING")
        if "value" not in ccols:
            conn.exec_driver_sql("ALTER TABLE currencies ADD COLUMN value REAL")
        tcols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(tasks)").all()
        }
        if "daily_rewards" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN daily_rewards STRING")
        if "weekly_rewards" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN weekly_rewards STRING")
        if "monthly_rewards" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN monthly_rewards STRING")
        if "daily_reward_state" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN daily_reward_state STRING")
        if "weekly_reward_state" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN weekly_reward_state STRING")
        if "monthly_reward_state" not in tcols:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN monthly_reward_state STRING")
        spcols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(spendings)").all()
        }
        if "reward_mode" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN reward_mode STRING")
        if "reward_items" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN reward_items STRING")
        if "last_reward_at" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN last_reward_at DATETIME")
        if "reward_once_granted" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN reward_once_granted BOOLEAN DEFAULT 0")
        if "pass_current_level" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN pass_current_level INTEGER")
        if "pass_max_level" not in spcols:
            conn.exec_driver_sql("ALTER TABLE spendings ADD COLUMN pass_max_level INTEGER")


def seed_games(db: Session) -> Dict[str, Game]:
    path = FILES_DIR / "GameDB.xlsx"
    rows = load_xlsx_rows(path)
    extra_rows = [
        {"Title": "엘든링", "StartDate": "2022년 4월 16일", "EndDate": "2024년 7월 14일"},
        {"Title": "할로우나이트:실크송", "StartDate": "2025년 9월 9일", "EndDate": "2025년 10월 1일"},
        {"Title": "발더스게이트3", "StartDate": "2024년 8월 10일", "EndDate": "2025년 1월 9일"},
    ]
    if not rows:
        rows = []
    else:
        headers = rows[0]
        header_len = len(headers)
        body = rows[1:]
        rows = [dict(zip(headers, (r + [""] * (header_len - len(r)))[:header_len])) for r in body]
    rows.extend(extra_rows)
    games: Dict[str, Game] = {}
    seen_titles = set()
    for row in rows:
        title = row.get("Title")
        if not title:
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        start_date = parse_date_value(row.get("StartDate"))
        end_date = parse_date_value(row.get("EndDate"))
        stop_play = parse_bool(row.get("StopPlay"), default=False)
        uid = row.get("UID") or None
        coupon_url = row.get("CouponURL") or None
        gacha_cost = parse_int(row.get("Gacha"), default=0) or 0
        memo = row.get("Memo") or None
        refresh_day = parse_refresh_day(row.get("RefreshDay"))
        refresh_time = parse_time_value(row.get("RefreshTime"))
        if title in REFRESH_DEFAULTS:
            def_day, def_time = REFRESH_DEFAULTS[title]
            refresh_day = refresh_day or def_day
            refresh_time = refresh_time or parse_time_value(def_time)
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
        game.gacha = gacha_cost
        game.memo = memo
        if refresh_day is not None:
            game.refresh_day = refresh_day
        if refresh_time is not None:
            game.refresh_time = refresh_time.strftime("%H:%M")
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
        if character:
            # 기존 유저 수정값을 덮어쓰지 않기 위해 seed는 신규 캐릭터만 추가
            continue
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
        ctype = normalize_currency_type(row.get("Type"))
        value = parse_float(row.get("Value"), default=1) or 1
        ts_date = parse_date_value(row.get("lateDate")) or dt.date.today()
        ts = dt.datetime.combine(ts_date, dt.time.min, dt.timezone.utc)
        entry = Currency(
            title=title,
            game=game,
            counts=counts,
            timestamp=ts,
            type=ctype,
            value=value,
        )
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
        if event:
            # 사용자 수정 이벤트를 덮어쓰지 않음
            continue
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


def seed_tasks(db: Session, games: Dict[str, Game]) -> Dict[str, Task]:
    path = FILES_DIR / "TaskDB.xlsx"
    rows = load_xlsx_rows(path)
    if not rows:
        return {}
    headers = rows[0]
    header_len = len(headers)
    body = rows[1:]
    row_dicts = [
        dict(zip(headers, (r + [""] * (header_len - len(r)))[:header_len]))
        for r in body
    ]
    tasks: Dict[str, Task] = {}
    now = dt.datetime.now(dt.timezone.utc)
    for row in row_dicts:
        game_title = row.get("GameDB")
        if not game_title:
            continue
        game = games.get(game_title)
        if not game:
            continue
        daily_list = parse_task_list(row.get("DailyTask"))
        weekly_list = parse_task_list(row.get("WeeklyTask"))
        monthly_list = parse_task_list(row.get("MonthlyTask"))
        task = db.execute(select(Task).where(Task.game_id == game.id)).scalar_one_or_none()
        if not task:
            task = Task(game=game)
            db.add(task)
        task.daily_tasks = ";".join(daily_list) if daily_list else None
        task.weekly_tasks = ";".join(weekly_list) if weekly_list else None
        task.monthly_tasks = ";".join(monthly_list) if monthly_list else None
        task.daily_state = _encode_state(_decode_state(task.daily_state, len(daily_list)))
        task.weekly_state = _encode_state(_decode_state(task.weekly_state, len(weekly_list)))
        task.monthly_state = _encode_state(_decode_state(task.monthly_state, len(monthly_list)))
        task.last_daily_reset = task.last_daily_reset or now
        task.last_weekly_reset = task.last_weekly_reset or now
        task.last_monthly_reset = task.last_monthly_reset or now
        tasks[game_title] = task
    db.flush()
    return tasks


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
            seed_tasks(db, games)
        backfill_seed_defaults(db)
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
    count: Optional[int]


class CurrencyTimeseries(BaseModel):
    title: str
    buckets: List[CurrencyTimeseriesBucket]
    from_date: dt.date
    to_date: dt.date


class TaskOut(BaseModel):
    id: int
    game_id: int
    daily_tasks: List[str]
    weekly_tasks: List[str]
    monthly_tasks: List[str]
    daily_rewards: List[List["RewardOut"]]
    weekly_rewards: List[List["RewardOut"]]
    monthly_rewards: List[List["RewardOut"]]
    daily_state: List[bool]
    weekly_state: List[bool]
    monthly_state: List[bool]
    daily_message: Optional[str] = None
    weekly_message: Optional[str] = None
    monthly_message: Optional[str] = None


class TaskStateUpdate(BaseModel):
    daily_state: Optional[List[bool]] = None
    weekly_state: Optional[List[bool]] = None
    monthly_state: Optional[List[bool]] = None


class TaskUpdate(BaseModel):
    daily_tasks: Optional[List[str]] = None
    weekly_tasks: Optional[List[str]] = None
    monthly_tasks: Optional[List[str]] = None
    daily_rewards: Optional[List[List["RewardIn"]]] = None
    weekly_rewards: Optional[List[List["RewardIn"]]] = None
    monthly_rewards: Optional[List[List["RewardIn"]]] = None


class RewardIn(BaseModel):
    title: str
    count: int = Field(..., description="지급/차감 수량(음수 허용)")


class RewardOut(BaseModel):
    title: str
    count: int


def decode_reward_list(raw: Optional[str]) -> List["RewardOut"]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = []
    if not isinstance(data, list):
        return []
    rewards: List[RewardOut] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        count = parse_int(item.get("count"), default=0) or 0
        if title:
            rewards.append(RewardOut(title=title, count=count))
    return rewards


def encode_reward_list(rows: List["RewardIn"]) -> str:
    serializable: List[Dict[str, object]] = []
    for r in rows:
        if not r.title.strip():
            continue
        serializable.append({"title": r.title.strip(), "count": int(r.count)})
    return json.dumps(serializable, ensure_ascii=False)


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
    gacha: Optional[int]
    gacha_pull_count: Optional[int] = 0
    gacha_pull_message: Optional[str] = None
    memo: Optional[str]
    refresh_day: Optional[int]
    refresh_time: Optional[str]
    daily_complete: bool = False
    weekly_complete: bool = False
    monthly_complete: bool = False

    @field_validator("uid", mode="before")
    def coerce_uid(cls, v):
        if v is None:
            return None
        return str(v)

    @field_serializer("uid")
    def serialize_uid(self, value):
        return str(value) if value is not None else None

    @field_serializer("refresh_time")
    def serialize_refresh_time(self, value):
        if value is None:
            return None
        if isinstance(value, dt.time):
            return value.strftime("%H:%M")
        return str(value)


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


class GameMemoUpdate(BaseModel):
    memo: Optional[str] = None


class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    counts: int
    timestamp: dt.datetime
    type: Optional[str]
    value: Optional[float]
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


class EventAlertOut(BaseModel):
    title: str
    type: str
    start_date: dt.date
    end_date: Optional[dt.date]
    game_title: str


class DashboardAlert(BaseModel):
    ongoing_count: int
    ongoing_events: List[EventAlertOut]
    tomorrow_refresh_titles: List[str]


class DashboardAlert(BaseModel):
    ongoing_count: int
    ongoing_events: List[EventAlertOut]
    tomorrow_refresh_titles: List[str]


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
    reward_mode: str | None = None
    rewards: List["RewardOut"] = []
    pass_current_level: Optional[int] = None
    pass_max_level: Optional[int] = None


class SpendingConfigUpdate(BaseModel):
    reward_mode: Optional[str] = None
    rewards: Optional[List["RewardIn"]] = None
    pass_current_level: Optional[int] = None
    pass_max_level: Optional[int] = None


TaskOut.model_rebuild()
TaskUpdate.model_rebuild()
SpendingOut.model_rebuild()
SpendingConfigUpdate.model_rebuild()


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

    @field_validator("type", mode="after")
    @classmethod
    def validate_type(cls, v):
        if v not in EVENT_TYPE_OPTIONS:
            raise ValueError(f"유효하지 않은 이벤트 분류입니다. {sorted(EVENT_TYPE_OPTIONS)} 중 선택하세요.")
        return v

    @field_validator("priority", mode="after")
    @classmethod
    def validate_priority(cls, v):
        if v not in EVENT_PRIORITY_OPTIONS:
            raise ValueError(f"유효하지 않은 중요도입니다. {sorted(EVENT_PRIORITY_OPTIONS)} 중 선택하세요.")
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


class SimpleRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self.hits: Dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> Tuple[bool, int]:
        now = time.time()
        with self.lock:
            q = self.hits.get(key)
            if q is None:
                q = deque()
                self.hits[key] = q
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry_after = int(self.window - (now - q[0]))
                return False, max(retry_after, 1)
            q.append(now)
            return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.all_limiter = SimpleRateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)
        self.mutation_limiter = SimpleRateLimiter(
            RATE_LIMIT_MUTATION_MAX, RATE_LIMIT_WINDOW
        )

    async def dispatch(self, request: Request, call_next):
        client_ip = "unknown"
        if request.client and request.client.host:
            client_ip = request.client.host
        method = request.method.upper()
        allowed, retry_after = self.all_limiter.allow(f"{client_ip}:all")
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests", "retry_after": retry_after},
            )
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            allowed_mut, retry_after_mut = self.mutation_limiter.allow(
                f"{client_ip}:mut"
            )
            if not allowed_mut:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many write requests", "retry_after": retry_after_mut},
                )
        response = await call_next(request)
        return response


def require_admin_token(request: Request):
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin token is not configured on the server.",
        )
    header_val = request.headers.get("x-admin-token") or ""
    if header_val.strip() != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token"
        )


app = FastAPI(title="Dashboard Backend", version="0.2.0")
app.add_middleware(RateLimitMiddleware)

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


@app.get("/auth/verify")
def verify_admin(_: None = Depends(require_admin_token)):
    return {"status": "ok"}


@app.post(
    "/items",
    response_model=ItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_token)],
)
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


@app.post(
    "/actions/click",
    response_model=ItemOut,
    dependencies=[Depends(require_admin_token)],
)
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


@app.get("/dashboard/alerts", response_model=DashboardAlert)
def dashboard_alerts(db: Session = Depends(get_db)):
    today = today_local()
    games = db.execute(select(Game)).scalars().all()
    rows = db.execute(
        select(GameEvent, Game.title)
        .join(Game, Game.id == GameEvent.game_id)
        .where(
            GameEvent.start_date <= today,
            (GameEvent.end_date.is_(None) | (GameEvent.end_date >= today)),
        )
        .order_by(GameEvent.start_date.asc(), GameEvent.id.asc())
    ).all()
    ongoing = [
        EventAlertOut(
            title=ev.title,
            type=ev.type,
            start_date=ev.start_date,
            end_date=ev.end_date,
            game_title=game_title,
        )
        for ev, game_title in rows
    ]

    tomorrow = today + dt.timedelta(days=1)
    # convert python weekday (Mon=0) to desired format (Sun=1)
    tomorrow_day = ((tomorrow.weekday() + 1) % 7) + 1
    refresh_titles: List[str] = []
    for g in games:
        refresh_day, _ = _game_refresh_info(g)
        if refresh_day == tomorrow_day:
            refresh_titles.append(g.title)
    refresh_titles.sort()

    return DashboardAlert(
        ongoing_count=len(ongoing),
        ongoing_events=ongoing,
        tomorrow_refresh_titles=refresh_titles,
    )


@app.get("/games", response_model=List[GameOut])
def list_games(
    during_play_only: bool = False,
    include_stopped: bool = True,
    db: Session = Depends(get_db),
) -> List[Game]:
    query = select(Game)
    if not include_stopped:
        query = query.where(Game.stop_play.is_(False))
    if during_play_only:
        query = query.where(Game.end_date.is_(None))
    games = list(db.execute(query).scalars().all())
    games.sort(key=lambda g: (g.stop_play, -g.playtime_days))
    game_ids = [g.id for g in games]

    tasks_by_game: Dict[int, Task] = {}
    if game_ids:
        task_rows = db.execute(select(Task).where(Task.game_id.in_(game_ids))).scalars().all()
        tasks_by_game = {t.game_id: t for t in task_rows}

    currency_latest: Dict[int, List[Currency]] = {}
    if game_ids:
        rows = (
            db.execute(
                select(Currency)
                .where(Currency.game_id.in_(game_ids))
                .order_by(Currency.game_id.asc(), Currency.title.asc(), Currency.timestamp.desc(), Currency.id.desc())
            )
            .scalars()
            .all()
        )
        temp: Dict[Tuple[int, str], Currency] = {}
        for r in rows:
            key = (r.game_id, r.title)
            if key not in temp:
                temp[key] = r
        for (gid, _), cur in temp.items():
            currency_latest.setdefault(gid, []).append(cur)

    changed = False
    for g in games:
        latest_cur = currency_latest.get(g.id, [])
        pull_count, pull_msg = compute_gacha_pull(g, db, latest_cur)
        g.gacha_pull_count = pull_count
        g.gacha_pull_message = pull_msg
        task = tasks_by_game.get(g.id)
        if task:
            changed = _ensure_task_resets(task, g, db) or changed
            lists = _task_lists(task)
            states = _task_states(task, lists)
            g.daily_complete = bool(states[0]) and all(states[0])
            g.weekly_complete = bool(states[1]) and all(states[1])
            g.monthly_complete = bool(states[2]) and all(states[2])
        else:
            g.daily_complete = False
            g.weekly_complete = False
            g.monthly_complete = False
        changed = _apply_spending_rewards(g, db) or changed
    if changed:
        db.commit()
    return games


def get_game_or_404(game_id: int, db: Session) -> Game:
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def get_latest_currencies(db: Session, game: Game) -> List[Currency]:
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


def get_task_or_404(game_id: int, db: Session) -> Task:
    task = db.execute(select(Task).where(Task.game_id == game_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def backfill_seed_defaults(db: Session) -> None:
    """
    Safely fills new columns using seed files without overriding user data.
    - games.gacha: set only when currently 0/None and seed has a positive value.
    - games.memo: set only when missing and seed has a memo value.
    - currencies.type/value: set only when missing/None, using latest entry per title.
    """
    if not FILES_DIR.exists():
        return
    games = db.execute(select(Game)).scalars().all()
    gacha_map = load_game_gacha_map()
    memo_map = load_game_memo_map()
    refresh_map = load_game_refresh_map()
    if gacha_map or memo_map:
        for game in games:
            if (game.gacha or 0) == 0 and gacha_map:
                gval = gacha_map.get(game.title)
                if gval and gval > 0:
                    game.gacha = gval
            if (not game.memo) and memo_map:
                m = memo_map.get(game.title)
                if m:
                    game.memo = m
    if refresh_map or REFRESH_DEFAULTS:
        for game in games:
            ref_day = game.refresh_day
            ref_time = game.refresh_time
            if game.title in refresh_map:
                day_val, time_val = refresh_map[game.title]
                if ref_day is None and day_val is not None:
                    ref_day = day_val
                if ref_time is None and time_val is not None:
                    ref_time = time_val.strftime("%H:%M")
            if game.title in REFRESH_DEFAULTS:
                def_day, def_time = REFRESH_DEFAULTS[game.title]
                if ref_day is None and def_day is not None:
                    ref_day = def_day
                if ref_time is None and def_time is not None:
                    ref_time = def_time
            game.refresh_day = ref_day
            game.refresh_time = ref_time
    currency_map = load_currency_meta_map()
    if currency_map:
        for game in games:
            latest = get_latest_currencies(db, game)
            for cur in latest:
                key = (game.title, cur.title)
                if key not in currency_map:
                    continue
                ctype, value = currency_map[key]
                if not cur.type:
                    cur.type = ctype
                if cur.value is None:
                    cur.value = value


def compute_gacha_pull(game: Game, db: Session, latest_currencies: Optional[List[Currency]] = None) -> Tuple[int, str]:
    if not game.gacha or game.gacha <= 0:
        return 0, "이 게임은 뽑기가 없는 게임이네요. 재밌게 즐기세요!"
    currencies = latest_currencies or get_latest_currencies(db, game)
    total_units = 0
    for cur in currencies:
        ctype = normalize_currency_type(cur.type)
        if ctype not in {"MAIN", "GACHA"}:
            continue
        value = cur.value if cur.value is not None else 1
        try:
            val = float(value)
        except (TypeError, ValueError):
            val = 1.0
        units = int(val * cur.counts)
        total_units += units
    pulls = total_units // game.gacha
    message = f"현재 보유 중인 재화로 {pulls}번 뽑기를 할 수 있어요!"
    return pulls, message


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
    return get_latest_currencies(db, game)


@app.get("/games/{game_id}/tasks", response_model=TaskOut)
def get_tasks(game_id: int, db: Session = Depends(get_db)) -> TaskOut:
    game = get_game_or_404(game_id, db)
    task = get_task_or_404(game.id, db)
    changed = _ensure_task_resets(task, game, db)
    changed = _apply_spending_rewards(game, db) or changed
    if changed:
        db.commit()
        db.refresh(task)
    return task_to_out(task, db)


@app.post(
    "/games/{game_id}/tasks/update",
    response_model=TaskOut,
    dependencies=[Depends(require_admin_token)],
)
def update_tasks(
    game_id: int, payload: TaskUpdate, db: Session = Depends(get_db)
) -> TaskOut:
    game = get_game_or_404(game_id, db)
    task = get_task_or_404(game.id, db)
    _ensure_task_resets(task, game, db)
    lists = list(_task_lists(task))
    states = list(_task_states(task, tuple(lists)))
    reward_states = list(_reward_states(task, tuple(lists)))
    rewards: List[List[List[RewardIn]]] = [
        [[RewardIn(title=r.title, count=r.count) for r in row] for row in decoded]
        for decoded in _task_rewards(task, tuple(lists))
    ]

    def apply_updates(idx: int, new_values: Optional[List[str]]):
        if new_values is None:
            return
        clean = [v.strip() for v in new_values if v and v.strip()]
        lists[idx] = clean
        states[idx] = states[idx][: len(clean)]
        if len(states[idx]) < len(clean):
            states[idx].extend([False] * (len(clean) - len(states[idx])))

    apply_updates(0, payload.daily_tasks)
    apply_updates(1, payload.weekly_tasks)
    apply_updates(2, payload.monthly_tasks)

    def apply_rewards(idx: int, new_rewards: Optional[List[List[RewardIn]]]):
        if new_rewards is None:
            return
        padded: List[List[RewardIn]] = []
        for row in new_rewards[: len(lists[idx])]:
            padded.append([RewardIn(title=r.title.strip(), count=r.count) for r in row if r.title.strip()])
        if len(padded) < len(lists[idx]):
            padded.extend([[] for _ in range(len(lists[idx]) - len(padded))])
        rewards[idx] = padded

    apply_rewards(0, payload.daily_rewards)
    apply_rewards(1, payload.weekly_rewards)
    apply_rewards(2, payload.monthly_rewards)

    def sync_reward_states(idx: int):
        reward_states[idx] = reward_states[idx][: len(lists[idx])]
        if len(reward_states[idx]) < len(lists[idx]):
            reward_states[idx].extend([False] * (len(lists[idx]) - len(reward_states[idx])))

    sync_reward_states(0)
    sync_reward_states(1)
    sync_reward_states(2)

    task.daily_tasks = encode_task_list(lists[0])
    task.weekly_tasks = encode_task_list(lists[1])
    task.monthly_tasks = encode_task_list(lists[2])
    task.daily_rewards = encode_rewards(rewards[0])
    task.weekly_rewards = encode_rewards(rewards[1])
    task.monthly_rewards = encode_rewards(rewards[2])
    task.daily_state = _encode_state(states[0])
    task.weekly_state = _encode_state(states[1])
    task.monthly_state = _encode_state(states[2])
    task.daily_reward_state = _encode_state(reward_states[0])
    task.weekly_reward_state = _encode_state(reward_states[1])
    task.monthly_reward_state = _encode_state(reward_states[2])
    db.commit()
    db.refresh(task)
    return task_to_out(task, db)


def _normalize_state(new_state: Optional[List[bool]], length: int, current: List[bool]) -> List[bool]:
    if new_state is None:
        return current
    vals = [bool(v) for v in new_state[:length]]
    if len(vals) < length:
        vals.extend([False] * (length - len(vals)))
    return vals


@app.post(
    "/tasks/{task_id}/state",
    response_model=TaskOut,
    dependencies=[Depends(require_admin_token)],
)
def update_task_state(task_id: int, payload: TaskStateUpdate, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    game = task.game or get_game_or_404(task.game_id, db)
    _ensure_task_resets(task, game, db)
    lists = _task_lists(task)
    rewards = _task_rewards(task, lists)
    prev_states = list(_task_states(task, lists))
    reward_states = list(_reward_states(task, lists))
    states = list(prev_states)
    states[0] = _normalize_state(payload.daily_state, len(lists[0]), states[0])
    states[1] = _normalize_state(payload.weekly_state, len(lists[1]), states[1])
    states[2] = _normalize_state(payload.monthly_state, len(lists[2]), states[2])
    reward_states[0] = _normalize_state(reward_states[0], len(lists[0]), reward_states[0])
    reward_states[1] = _normalize_state(reward_states[1], len(lists[1]), reward_states[1])
    reward_states[2] = _normalize_state(reward_states[2], len(lists[2]), reward_states[2])
    _apply_reward_on_completion(game, rewards, prev_states, states, reward_states, db)
    task.daily_state = _encode_state(states[0])
    task.weekly_state = _encode_state(states[1])
    task.monthly_state = _encode_state(states[2])
    task.daily_reward_state = _encode_state(reward_states[0])
    task.weekly_reward_state = _encode_state(reward_states[1])
    task.monthly_reward_state = _encode_state(reward_states[2])
    db.commit()
    db.refresh(task)
    return task_to_out(task, db)


@app.post(
    "/currencies/{currency_id}/adjust",
    response_model=CurrencyOut,
    dependencies=[Depends(require_admin_token)],
)
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
        type=currency.type,
        value=currency.value,
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
    result = db.execute(select(Spending).where(Spending.game_id == game.id))
    spendings = result.scalars().all()
    spendings.sort(key=lambda s: s.next_paying_date)
    return [_spending_to_out(s) for s in spendings]


@app.post(
    "/games/{game_id}/end",
    response_model=GameOut,
    dependencies=[Depends(require_admin_token)],
)
def end_game(game_id: int, payload: GameEndPayload, db: Session = Depends(get_db)):
    game = get_game_or_404(game_id, db)
    game.end_date = payload.end_date or dt.date.today()
    game.stop_play = True
    db.commit()
    db.refresh(game)
    return game


@app.post(
    "/spendings/{spending_id}/renew",
    response_model=SpendingOut,
    dependencies=[Depends(require_admin_token)],
)
def renew_spending(
    spending_id: int, payload: SpendingAdjust, db: Session = Depends(get_db)
):
    spending = db.get(Spending, spending_id)
    if not spending:
        raise HTTPException(status_code=404, detail="Spending not found")
    base_days = spending.expiration_days
    if payload.expiration_days is not None:
        base_days = payload.expiration_days
    today = dt.date.today()
    mode = _spending_reward_mode(spending)
    remain = spending.remain_date
    if payload.paying_date:
        spending.paying_date = payload.paying_date
    else:
        spending.paying_date = today
    if mode == "DAILY" and remain >= 1:
        spending.expiration_days = base_days + remain
    else:
        spending.expiration_days = base_days
    if payload.paying is not None:
        spending.paying = payload.paying
    spending.reward_once_granted = False
    spending.last_reward_at = None
    db.commit()
    db.refresh(spending)
    return _spending_to_out(spending)


@app.post(
    "/spendings/{spending_id}/configure",
    response_model=SpendingOut,
    dependencies=[Depends(require_admin_token)],
)
def configure_spending(
    spending_id: int, payload: SpendingConfigUpdate, db: Session = Depends(get_db)
) -> SpendingOut:
    spending = db.get(Spending, spending_id)
    if not spending:
        raise HTTPException(status_code=404, detail="Spending not found")
    if payload.reward_mode:
        mode = payload.reward_mode.upper()
        if mode not in {"DAILY", "ONCE"}:
            raise HTTPException(status_code=400, detail="reward_mode must be DAILY or ONCE")
        spending.reward_mode = mode
    if payload.rewards is not None:
        spending.reward_items = encode_reward_list(payload.rewards)
        spending.reward_once_granted = False
        spending.last_reward_at = None
    if payload.pass_max_level is not None:
        if payload.pass_max_level <= 0:
            raise HTTPException(status_code=400, detail="pass_max_level must be positive")
        spending.pass_max_level = payload.pass_max_level
    if payload.pass_current_level is not None:
        if payload.pass_current_level < 0:
            raise HTTPException(status_code=400, detail="pass_current_level must be >= 0")
        spending.pass_current_level = payload.pass_current_level
    if spending.pass_max_level and spending.pass_current_level:
        if spending.pass_current_level > spending.pass_max_level:
            raise HTTPException(status_code=400, detail="pass_current_level cannot exceed pass_max_level")
    db.commit()
    db.refresh(spending)
    return _spending_to_out(spending)


@app.post(
    "/games/{game_id}/events",
    response_model=GameEventOut,
    status_code=201,
    dependencies=[Depends(require_admin_token)],
)
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


@app.put(
    "/games/{game_id}/events/{event_id}",
    response_model=GameEventOut,
    dependencies=[Depends(require_admin_token)],
)
def update_game_event(
    game_id: int, event_id: int, payload: EventCreate, db: Session = Depends(get_db)
):
    game = get_game_or_404(game_id, db)
    event = db.get(GameEvent, event_id)
    if not event or event.game_id != game.id:
        raise HTTPException(status_code=404, detail="Event not found")
    event.title = payload.title
    event.type = payload.type
    event.start_date = payload.start_date
    event.end_date = payload.end_date
    event.priority = payload.priority
    db.commit()
    db.refresh(event)
    return event


@app.post(
    "/games/{game_id}/memo",
    response_model=GameOut,
    dependencies=[Depends(require_admin_token)],
)
def update_game_memo(
    game_id: int, payload: GameMemoUpdate, db: Session = Depends(get_db)
):
    game = get_game_or_404(game_id, db)
    game.memo = payload.memo or None
    db.commit()
    db.refresh(game)
    pull_count, pull_msg = compute_gacha_pull(game, db)
    game.gacha_pull_count = pull_count
    game.gacha_pull_message = pull_msg
    return game


@app.post(
    "/characters/{character_id}/update",
    response_model=CharacterOut,
    dependencies=[Depends(require_admin_token)],
)
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
            in_range.sort(key=lambda e: (_ts(e.timestamp), e.id), reverse=True)
            return in_range[0].counts
        return _latest_count_on_or_before(entries, end_date, title=title)

    # ALL: sum per title using their own max-or-latest in range
    titles = {e.title for e in entries}
    total = 0
    for t in titles:
        total += _max_or_latest_in_range(entries, start_date, end_date, title=t)
    return total


def _game_refresh_info(game: Game) -> Tuple[Optional[int], dt.time]:
    day = game.refresh_day
    time_val = parse_time_value(game.refresh_time)
    if game.title in REFRESH_DEFAULTS:
        def_day, def_time = REFRESH_DEFAULTS[game.title]
        day = day or def_day
        time_val = time_val or parse_time_value(def_time)
    return day, time_val or dt.time(5, 0)


def _most_recent_daily(now: dt.datetime, refresh_time: dt.time) -> dt.datetime:
    # refresh_time is treated as LOCAL_TZ (KST) so resets match in-game schedule
    rt = refresh_time
    if rt.tzinfo is None:
        rt = rt.replace(tzinfo=LOCAL_TZ)
    candidate = dt.datetime.combine(now.date(), rt)
    if candidate > now:
        candidate -= dt.timedelta(days=1)
    return candidate


def _most_recent_weekly(
    now: dt.datetime, refresh_time: dt.time, refresh_day: int
) -> dt.datetime:
    # refresh_day: 1=Sunday ... 7=Saturday
    target_py = (refresh_day + 5) % 7  # python weekday: Monday=0
    days_back = (now.weekday() - target_py) % 7
    date = (now - dt.timedelta(days=days_back)).date()
    rt = refresh_time
    if rt.tzinfo is None:
        rt = rt.replace(tzinfo=LOCAL_TZ)
    candidate = dt.datetime.combine(date, rt)
    if candidate > now:
        candidate -= dt.timedelta(days=7)
    return candidate


def _most_recent_monthly(now: dt.datetime, refresh_time: dt.time) -> dt.datetime:
    rt = refresh_time
    if rt.tzinfo is None:
        rt = rt.replace(tzinfo=LOCAL_TZ)
    anchor = dt.datetime.combine(now.replace(day=1).date(), rt)
    if anchor > now:
        prev_month = (now.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        anchor = dt.datetime.combine(prev_month.date(), rt)
    return anchor


def _needs_reset(last: Optional[dt.datetime], target: dt.datetime) -> bool:
    if last is None:
        return True
    return _ts(last) < _ts(target)


def _task_lists(task: Task) -> Tuple[List[str], List[str], List[str]]:
    return (
        parse_task_list(task.daily_tasks),
        parse_task_list(task.weekly_tasks),
        parse_task_list(task.monthly_tasks),
    )


def _task_states(task: Task, lists: Tuple[List[str], List[str], List[str]]) -> Tuple[List[bool], List[bool], List[bool]]:
    daily_list, weekly_list, monthly_list = lists
    return (
        _decode_state(task.daily_state, len(daily_list)),
        _decode_state(task.weekly_state, len(weekly_list)),
        _decode_state(task.monthly_state, len(monthly_list)),
    )


def _task_rewards(
    task: Task, lists: Tuple[List[str], List[str], List[str]]
) -> Tuple[List[List[RewardOut]], List[List[RewardOut]], List[List[RewardOut]]]:
    daily_list, weekly_list, monthly_list = lists
    return (
        decode_rewards(task.daily_rewards, len(daily_list)),
        decode_rewards(task.weekly_rewards, len(weekly_list)),
        decode_rewards(task.monthly_rewards, len(monthly_list)),
    )


def _reward_states(
    task: Task, lists: Tuple[List[str], List[str], List[str]]
) -> Tuple[List[bool], List[bool], List[bool]]:
    daily_list, weekly_list, monthly_list = lists
    return (
        _decode_state(task.daily_reward_state, len(daily_list)),
        _decode_state(task.weekly_reward_state, len(weekly_list)),
        _decode_state(task.monthly_reward_state, len(monthly_list)),
    )


def _apply_reward_on_completion(
    game: Game,
    rewards: Tuple[List[List[RewardOut]], List[List[RewardOut]], List[List[RewardOut]]],
    prev_states: List[List[bool]],
    next_states: List[List[bool]],
    reward_states: List[List[bool]],
    db: Session,
) -> None:
    for idx in range(3):
        reward_rows = rewards[idx] if idx < len(rewards) else []
        prev = prev_states[idx] if idx < len(prev_states) else []
        nxt = next_states[idx] if idx < len(next_states) else []
        rstates = reward_states[idx] if idx < len(reward_states) else []
        for i, state_now in enumerate(nxt):
            was = prev[i] if i < len(prev) else False
            already = rstates[i] if i < len(rstates) else False
            if state_now and not was and not already:
                for rew in reward_rows[i] if i < len(reward_rows) else []:
                    _grant_currency(game, rew, db)
                if i < len(rstates):
                    rstates[i] = True


def _apply_spending_rewards(game: Game, db: Session) -> bool:
    now = dt.datetime.now(LOCAL_TZ)
    _, refresh_time = _game_refresh_info(game)
    anchor_daily = _most_recent_daily(now, refresh_time)
    spendings = db.execute(select(Spending).where(Spending.game_id == game.id)).scalars().all()
    changed = False
    today = today_local()
    for sp in spendings:
        mode = _spending_reward_mode(sp)
        rewards = _spending_rewards(sp)
        if not rewards:
            continue
        if sp.next_paying_date < today:
            continue
        if mode == "DAILY":
            last = sp.last_reward_at
            if _needs_reset(last, anchor_daily):
                for rew in rewards:
                    _grant_currency(game, rew, db)
                sp.last_reward_at = anchor_daily
                changed = True
        else:
            if not sp.reward_once_granted:
                if sp.pass_max_level and sp.pass_current_level is not None:
                    threshold = int(sp.pass_max_level * 0.75)
                    if sp.pass_current_level < threshold:
                        continue
                for rew in rewards:
                    _grant_currency(game, rew, db)
                sp.reward_once_granted = True
                changed = True
    if changed:
        db.flush()
    return changed


def _spending_to_out(spending: "Spending") -> "SpendingOut":
    rewards = _spending_rewards(spending)
    mode = _spending_reward_mode(spending)
    return SpendingOut(
        id=spending.id,
        game_id=spending.game_id,
        title=spending.title,
        paying=spending.paying,
        paying_date=spending.paying_date,
        type=spending.type,
        expiration_days=spending.expiration_days,
        next_paying_date=spending.next_paying_date,
        remain_date=spending.remain_date,
        is_repaying=spending.is_repaying,
        reward_mode=mode,
        rewards=rewards,
        pass_current_level=spending.pass_current_level,
        pass_max_level=spending.pass_max_level,
    )


def _grant_currency(game: Game, reward: RewardOut, db: Session) -> None:
    if not reward.title or reward.count is None:
        return
    count = int(reward.count)
    if count == 0:
        return
    latest = get_latest_currencies(db, game)
    latest_map = {c.title: c for c in latest}
    cur = latest_map.get(reward.title)
    new_counts = (cur.counts if cur else 0) + count
    if new_counts < 0:
        new_counts = 0
    new_entry = Currency(
        title=reward.title,
        game=game,
        counts=new_counts,
        timestamp=dt.datetime.now(dt.timezone.utc),
        type=cur.type if cur else None,
        value=cur.value if cur else None,
    )
    db.add(new_entry)


def _ensure_task_resets(task: Task, game: Game, db: Session) -> bool:
    changed = False
    now = dt.datetime.now(LOCAL_TZ)
    refresh_day, refresh_time = _game_refresh_info(game)
    lists = _task_lists(task)
    daily_list, weekly_list, monthly_list = lists
    states = list(_task_states(task, lists))
    reward_states = list(_reward_states(task, lists))

    recent_daily = _most_recent_daily(now, refresh_time)
    if _needs_reset(task.last_daily_reset, recent_daily):
        if daily_list:
            db.add(
                    TaskHistory(
                    task=task,
                    daily_done=int(all(states[0])) if states[0] else 0,
                    timestamp=recent_daily,
                )
            )
        states[0] = [False] * len(daily_list)
        reward_states[0] = [False] * len(daily_list)
        task.daily_state = _encode_state(states[0])
        task.daily_reward_state = _encode_state(reward_states[0])
        task.last_daily_reset = recent_daily
        changed = True

    if refresh_day:
        recent_weekly = _most_recent_weekly(now, refresh_time, refresh_day)
        if _needs_reset(task.last_weekly_reset, recent_weekly):
            if weekly_list:
                db.add(
                    TaskHistory(
                    task=task,
                    weekly_done=int(all(states[1])) if states[1] else 0,
                    timestamp=recent_weekly,
                )
            )
        states[1] = [False] * len(weekly_list)
        reward_states[1] = [False] * len(weekly_list)
        task.weekly_state = _encode_state(states[1])
        task.weekly_reward_state = _encode_state(reward_states[1])
        task.last_weekly_reset = recent_weekly
        changed = True

    recent_monthly = _most_recent_monthly(now, refresh_time)
    if _needs_reset(task.last_monthly_reset, recent_monthly):
        if monthly_list:
            db.add(
                TaskHistory(
                    task=task,
                    monthly_done=int(all(states[2])) if states[2] else 0,
                    timestamp=recent_monthly,
                )
            )
        states[2] = [False] * len(monthly_list)
        reward_states[2] = [False] * len(monthly_list)
        task.monthly_state = _encode_state(states[2])
        task.monthly_reward_state = _encode_state(reward_states[2])
        task.last_monthly_reset = recent_monthly
        changed = True
    db.flush()
    return changed

def _latest_history(task: Task, db: Session, field: str) -> Optional[int]:
    col = getattr(TaskHistory, field)
    row = (
        db.execute(
            select(TaskHistory)
            .where(TaskHistory.task_id == task.id, col.is_not(None))
            .order_by(TaskHistory.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        return None
    return getattr(row, field)


def _task_messages(task: Task, db: Session) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    daily_prev = _latest_history(task, db, "daily_done")
    weekly_prev = _latest_history(task, db, "weekly_done")
    monthly_prev = _latest_history(task, db, "monthly_done")
    daily_msg = None
    weekly_msg = None
    monthly_msg = None
    if daily_prev is not None:
        daily_msg = (
            "어제는 숙제를 다 했어요! 오늘도 화이팅!"
            if daily_prev
            else "어제는 숙제를 다 못 했네요. 오늘은 화이팅!"
        )
    if weekly_prev is not None:
        weekly_msg = (
            "지난 주 숙제도 완료! 이번 주도 화이팅!"
            if weekly_prev
            else "지난 주는 숙제를 다 못 했네요. 이번 주는 화이팅!"
        )
    if monthly_prev is not None:
        monthly_msg = (
            "지난 달 숙제 클리어! 이번 달도 화이팅!"
            if monthly_prev
            else "지난 달은 숙제를 다 못 했네요. 이번 달은 화이팅!"
        )
    return daily_msg, weekly_msg, monthly_msg


def task_to_out(task: Task, db: Session) -> TaskOut:
    lists = _task_lists(task)
    states = _task_states(task, lists)
    rewards = _task_rewards(task, lists)
    daily_msg, weekly_msg, monthly_msg = _task_messages(task, db)
    return TaskOut(
        id=task.id,
        game_id=task.game_id,
        daily_tasks=lists[0],
        weekly_tasks=lists[1],
        monthly_tasks=lists[2],
        daily_rewards=rewards[0],
        weekly_rewards=rewards[1],
        monthly_rewards=rewards[2],
        daily_state=states[0],
        weekly_state=states[1],
        monthly_state=states[2],
        daily_message=daily_msg,
        weekly_message=weekly_msg,
        monthly_message=monthly_msg,
    )


@app.get("/games/{game_id}/currencies/timeseries", response_model=CurrencyTimeseries)
def currency_timeseries(
    game_id: int,
    title: Optional[str] = None,
    days: int = 7,
    weekly: bool = False,
    weeks: int = 8,
    start_date: Optional[dt.date] = None,
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
    today = dt.date.today()

    if weekly:
        weeks = max(1, min(weeks, 15))
        if start_date:
            buckets: List[CurrencyTimeseriesBucket] = []
            anchor_idx = max(0, weeks - 3)  # place anchor at third from right
            last_count: Optional[int] = None
            for i in range(weeks):
                offset = i - anchor_idx
                week_start = start_date + dt.timedelta(days=7 * offset)
                week_end = week_start + dt.timedelta(days=6)
                count = None
                if week_start <= today:
                    count = _max_or_latest_in_range(entries, week_start, week_end, title=title)
                if count is None:
                    count = last_count
                else:
                    last_count = count
                buckets.append(CurrencyTimeseriesBucket(date=week_end, count=count))
            return CurrencyTimeseries(
                title=title or "ALL",
                buckets=buckets,
                from_date=buckets[0].date,
                to_date=buckets[-1].date,
            )
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
