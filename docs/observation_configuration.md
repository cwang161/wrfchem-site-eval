# Observation configuration

## Standard chemistry input

Chemistry observations use the `chem_qc` combined-wide profile. Every row is
one station and timestamp. Required identity columns are configured rather
than hard-coded; pollutant columns are optional unless `required: true`.

```text
Time,code,latitude,longitude,pm25,no2,so2,o3,pm25_qc_flag,...
```

The reader returns canonical columns:

```text
station_id,time,latitude,longitude,pm25,no2,so2,o3,pm25_qc_flag,...
```

`accepted_qc_flags` controls which values remain available for evaluation.
The flag column itself is always retained. The default example accepts only
`valid`; omitted or rejected values become missing without deleting the row.

## ISD hourly meteorology

The `isd_hourly_met` profile uses the same combined-wide reader plus explicit
scale and offset rules. The example converts tenths of degrees Celsius to
kelvin, tenths of metres per second to metres per second, and derives relative
humidity from temperature and dew point.

## Duplicate and coordinate rules

The canonical key is `station_id + time`. Duplicate keys raise an error by
default; `duplicate_policy` may be set to `first` or `last` only when that is a
deliberate source-data rule. A station must have one stable latitude/longitude
pair. Coordinate changes larger than `1e-5` degrees are rejected before grid
mapping.

## Time zones

`time.timezone` describes the timestamps in the source file and
`time.output_timezone` defaults to UTC. Canonical timestamps are stored as
timezone-naive UTC values by default, matching WRF `Times` conventions.
