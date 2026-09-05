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

`isd_met_with_gsod.yaml` demonstrates `combined_sources`: ISD hourly variables
and GSOD daily precipitation are coalesced by station/time. GSOD `PRCP` is
converted from inches to mm and its accepted `PRCP_ATTRIBUTES` values are set
in YAML. This preserves one consolidated met output while allowing a different
precipitation source. The station IDs in the two source files must use the same
canonical convention.

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

## Matching and precipitation

Case configuration accepts an optional nearest-time tolerance and aggregation
frequency. For example, `frequency: 1D` sums precipitation per station and
averages other numeric variables before matching. WRF RAINC + RAINNC + optional
RAINSH is converted from cumulative to interval precipitation separately for
every station; counter resets are handled and the first interval is missing.
`observation_minimum_count` and `model_minimum_count` can use different
completeness requirements. For GSOD, the former can be 1 and the latter 20
hourly WRF intervals per day. It may also be a mapping such as
`{default: 20, precipitation: 1}` for combined hourly ISD and daily GSOD.
`offset` shifts aggregation boundaries when an
observation product uses a non-midnight end-of-day convention.

## Chemistry model units

PM2.5 and PM10 retain WRF mass concentrations. Gas fields labelled ppmv are
converted with surface pressure, 2-m temperature and molar mass. O3, NO2, SO2,
NO and NH3 output ug m-3; CO outputs mg m-3 to match the supplied template.
