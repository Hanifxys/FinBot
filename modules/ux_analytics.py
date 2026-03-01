import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from modules.redis_mgr import RedisManager

logger = logging.getLogger(__name__)


UX_EVENTS = {
    "preview_shown",
    "confirm",
    "edit",
    "cancel",
    "history_filter_used",
    "insight_action_clicked",
    "reminder_snooze",
    "recurring_suggestion_shown",
    "recurring_suggestion_accepted",
    "recurring_suggestion_dismissed",
    "autopilot_suggested",
    "autopilot_approved",
    "autopilot_rejected",
    "voice_entry_processed",
    "manual_entry_processed",
    "onboarding_step_done",
}


@dataclass
class PrivacyConfig:
    consent_ttl_seconds: int = 365 * 24 * 3600


class UXAnalytics:
    """
    Lightweight event tracking with privacy-by-design:
    - user ids are hashed before persistence
    - explicit opt-out via consent key
    - offline queue when Redis is unavailable
    """

    def __init__(self) -> None:
        self.redis = RedisManager()
        self.privacy = PrivacyConfig()
        self.offline_file = os.getenv("UX_OFFLINE_QUEUE_FILE", "temp_reports/ux_event_queue.jsonl")

    @staticmethod
    def _hash_user_id(user_id: int) -> str:
        return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:20]

    def _consent_key(self, user_id: int) -> str:
        return f"user:{user_id}:telemetry_consent"

    def set_consent(self, user_id: int, allowed: bool) -> bool:
        if not self.redis.client:
            return False
        try:
            self.redis.client.setex(
                self._consent_key(user_id),
                self.privacy.consent_ttl_seconds,
                "1" if allowed else "0",
            )
            return True
        except Exception:
            return False

    def is_allowed(self, user_id: int) -> bool:
        """
        Default allow unless user explicitly opts out.
        """
        if not self.redis.client:
            return True
        try:
            raw = self.redis.client.get(self._consent_key(user_id))
            if raw is None:
                return True
            val = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
            return val != "0"
        except Exception:
            return True

    def _enqueue_offline(self, payload: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self.offline_file), exist_ok=True)
            with open(self.offline_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed writing offline UX queue: %s", exc)

    def flush_offline_queue(self, max_rows: int = 1000) -> int:
        if not self.redis.client:
            return 0
        if not os.path.exists(self.offline_file):
            return 0
        sent = 0
        try:
            with open(self.offline_file, "r", encoding="utf-8") as f:
                rows = f.readlines()
            remain: List[str] = []
            for idx, line in enumerate(rows):
                if idx >= max_rows:
                    remain.extend(rows[idx:])
                    break
                try:
                    item = json.loads(line.strip())
                    self.redis.client.lpush("ux:events", json.dumps(item, ensure_ascii=False))
                    sent += 1
                except Exception:
                    remain.append(line)
            with open(self.offline_file, "w", encoding="utf-8") as f:
                f.writelines(remain)
            return sent
        except Exception as exc:
            logger.warning("Failed flushing offline queue: %s", exc)
            return sent

    def track(
        self,
        *,
        user_id: int,
        event: str,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        if event not in UX_EVENTS:
            return
        if not self.is_allowed(user_id):
            return

        payload = {
            "event": event,
            "user_hash": self._hash_user_id(user_id),
            "timestamp": int(time.time()),
            "props": props or {},
        }

        if not self.redis.client:
            self._enqueue_offline(payload)
            return

        try:
            if os.path.exists(self.offline_file):
                self.flush_offline_queue(max_rows=200)
            self.redis.client.lpush("ux:events", json.dumps(payload, ensure_ascii=False))
            self.redis.client.ltrim("ux:events", 0, 50000)
        except Exception:
            self._enqueue_offline(payload)

    def _read_events(self, days: int = 7) -> List[Dict[str, Any]]:
        if not self.redis.client:
            return []
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
        out: List[Dict[str, Any]] = []
        try:
            for raw in self.redis.client.lrange("ux:events", 0, 50000):
                if not raw:
                    continue
                item = json.loads(raw)
                if int(item.get("timestamp", 0)) >= cutoff:
                    out.append(item)
        except Exception:
            return []
        return out

    def funnel_summary(self, days: int = 7) -> Dict[str, Any]:
        events = self._read_events(days=days)
        stages = ["preview_shown", "confirm"]
        counts = {s: 0 for s in stages}
        edits = cancels = 0
        recurring_shown = recurring_accepted = 0
        onboarding_steps = 0
        for e in events:
            ev = e.get("event")
            if ev in counts:
                counts[ev] += 1
            if ev == "edit":
                edits += 1
            if ev == "cancel":
                cancels += 1
            if ev == "recurring_suggestion_shown":
                recurring_shown += 1
            if ev == "recurring_suggestion_accepted":
                recurring_accepted += 1
            if ev == "onboarding_step_done":
                onboarding_steps += 1

        preview = counts["preview_shown"]
        confirm = counts["confirm"]
        conv = (confirm / preview * 100.0) if preview else 0.0
        dropoff = 100.0 - conv if preview else 0.0
        recurring_accept = (recurring_accepted / recurring_shown * 100.0) if recurring_shown else 0.0
        return {
            "window_days": days,
            "events_total": len(events),
            "counts": counts,
            "conversion_rate_preview_to_confirm_pct": round(conv, 2),
            "dropoff_pct": round(dropoff, 2),
            "edit_rate_pct": round((edits / preview * 100.0), 2) if preview else 0.0,
            "cancel_rate_pct": round((cancels / preview * 100.0), 2) if preview else 0.0,
            "recurring_acceptance_rate_pct": round(recurring_accept, 2),
            "onboarding_step_events": onboarding_steps,
        }

    def actionable_report(self, days: int = 7) -> Dict[str, Any]:
        s = self.funnel_summary(days=days)
        actions: List[str] = []
        if s["dropoff_pct"] > 40:
            actions.append("Tingkatkan kejelasan draft transaksi sebelum konfirmasi.")
        if s["edit_rate_pct"] > 30:
            actions.append("Kategori/nominal sering salah: prioritaskan improving parser dan suggestions.")
        if s["cancel_rate_pct"] > 20:
            actions.append("Tambah context hint sebelum simpan untuk menurunkan cancel rate.")
        if s.get("recurring_acceptance_rate_pct", 0.0) < 25:
            actions.append("Recurring acceptance rendah: naikkan relevansi copy dan timing saran recurring.")
        if not actions:
            actions.append("Funnel sehat. Lanjutkan A/B test copy CTA untuk optimasi incremental.")
        return {"summary": s, "actions": actions}

    def monitoring_alerts(self, days: int = 2) -> List[Dict[str, Any]]:
        s = self.funnel_summary(days=days)
        alerts: List[Dict[str, Any]] = []
        if s["conversion_rate_preview_to_confirm_pct"] < 50:
            alerts.append({"level": "warning", "msg": "UX conversion below 50%."})
        if s["cancel_rate_pct"] > 25:
            alerts.append({"level": "warning", "msg": "Cancel rate above 25%."})
        return alerts
