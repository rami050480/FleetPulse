"""Fleet analytics service — overview, per-location breakdown, trip stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from geotab_client import GeotabClient
from models import FleetOverview, LocationStats, Vehicle, VehiclePosition, VehicleStatus

# K1 Logistics / K1 Group locations (FTW, Justin, OKC, Kansas City)
LOCATIONS = [
    {"name": "Fort Worth Yard", "address": "4200 Gravel Dr, Fort Worth, TX 76118", "lat": 32.8012, "lon": -97.2197},
    {"name": "Justin Terminal", "address": "17176 FM156, Justin, TX 76247", "lat": 33.0848, "lon": -97.2961},
    {"name": "OKC Terminal", "address": "4012 S Purdue Ave, Oklahoma City, OK 73179", "lat": 35.3922, "lon": -97.5900},
    {"name": "Kansas City Terminal", "address": "11200 N Congress Ave, Kansas City, MO 64153", "lat": 39.2967, "lon": -94.6680},
]


def _classify_status(device_status: dict[str, Any]) -> VehicleStatus:
    """Classify a vehicle as active/idle/parked based on DeviceStatusInfo."""
    speed = device_status.get("speed", 0) or 0
    is_driving = device_status.get("isDriving", False)
    if is_driving or speed > 3:
        return VehicleStatus.ACTIVE
    if speed > 0:
        return VehicleStatus.IDLE
    return VehicleStatus.PARKED


def _nearest_location(lat: float, lon: float) -> str | None:
    """Return nearest K1 location name if within ~500 m."""
    best, best_dist = None, 0.005  # ~500 m in degrees
    for loc in LOCATIONS:
        d = ((lat - loc["lat"]) ** 2 + (lon - loc["lon"]) ** 2) ** 0.5
        if d < best_dist:
            best, best_dist = loc["name"], d
    return best


def get_fleet_overview() -> FleetOverview:
    client = GeotabClient.get()
    devices = client.get_devices()
    statuses = client.get_device_status_info()
    status_map = {s.get("device", {}).get("id"): s for s in statuses}

    counts = {"active": 0, "idle": 0, "parked": 0, "offline": 0}
    for dev in devices:
        sid = dev.get("id")
        st = status_map.get(sid)
        if st:
            c = _classify_status(st).value
            counts[c] = counts.get(c, 0) + 1
        else:
            counts["offline"] += 1

    now = datetime.now(timezone.utc)
    trips = client.get_trips(now - timedelta(days=1), now)
    total_dist = sum(t.get("distance", 0) for t in trips)
    durations = [
        (t.get("stopDateTime", now) - t.get("startDateTime", now)).total_seconds() / 60
        for t in trips
        if isinstance(t.get("stopDateTime"), datetime)
        and isinstance(t.get("startDateTime"), datetime)
    ]

        # Convert km to miles for K1 Logistics (US operations)
    KM_TO_MILES = 0.621371
    LITERS_TO_GALLONS = 0.264172
    total_dist_miles = total_dist * KM_TO_MILES
    return FleetOverview(
        total_vehicles=len(devices),
        active=counts["active"],
        idle=counts["idle"],
        parked=counts["parked"],
        offline=counts["offline"],
        total_trips_today=len(trips),
        total_distance_miles=round(total_dist_miles, 1),
        avg_trip_duration_min=round(sum(durations) / max(len(durations), 1), 1),
        avg_trip_distance_miles=round(total_dist_miles / max(len(trips), 1), 1),
    )

def get_vehicles() -> list[Vehicle]:
    client = GeotabClient.get()
    devices = client.get_devices()
    statuses = client.get_device_status_info()
    status_map = {s.get("device", {}).get("id"): s for s in statuses}

    vehicles: list[Vehicle] = []
    for dev in devices:
        sid = dev.get("id")
        st = status_map.get(sid, {})
        lat = st.get("latitude", 0) or 0
        lon = st.get("longitude", 0) or 0
        vehicles.append(
            Vehicle(
                id=sid or "",
                name=dev.get("name", "Unknown"),
                status=_classify_status(st) if st else VehicleStatus.OFFLINE,
                position=VehiclePosition(
                    latitude=lat,
                    longitude=lon,
                    bearing=st.get("bearing", 0) or 0,
                    speed=st.get("speed", 0) or 0,
                )
                if lat and lon
                else None,
                location_name=_nearest_location(lat, lon) if lat and lon else None,
                last_contact=st.get("dateTime"),
            )
        )
    return vehicles


def get_location_stats() -> list[LocationStats]:
    vehicles = get_vehicles()
    stats: list[LocationStats] = []
    for loc in LOCATIONS:
        at_loc = [v for v in vehicles if v.location_name == loc["name"]]
        stats.append(
            LocationStats(
                name=loc["name"],
                address=loc["address"],
                latitude=loc["lat"],
                longitude=loc["lon"],
                vehicle_count=len(at_loc),
                active=sum(1 for v in at_loc if v.status == VehicleStatus.ACTIVE),
            )
        )
    return stats
