# Choosing a shard key for a time series of sensor readings

Sensor fleets write small records at a steady rate and read them back in
windows: the last hour for one device, the last day for one site, the last week
for the whole fleet. A shard key that serves one of those reads well tends to
punish another, so the choice deserves more thought than hashing the device id.

## Why a pure time key fails

Keying by timestamp keeps every recent write on the newest shard. Ingest then
lands on a single machine while the rest of the cluster idles, and the hot shard
is also the one every dashboard reads. Rebalancing does not help, because the
next hour is always new.

## Why a pure device key fails

Hashing the device identifier spreads writes evenly, but a query for one site
now fans out to every shard, since devices from the same site hash to unrelated
places. Fleet wide queries are no worse than before, yet the most common
operator view becomes the most expensive one.

## A compound key with a bucket

The layout that held up in our tests prefixes a site identifier, then a coarse
time bucket of one day, then the device identifier. Writes for a single day
spread across sites, a site query touches one prefix, and a device query adds
the device suffix to that same prefix. Old buckets become immutable, which lets
them move to cheaper storage without touching the live tier.

The cost is a hard limit on how skewed a single site may be. One site with a
third of all devices still creates a hot prefix, and the fix there is to split
that site into virtual sub sites by a stable function of the device identifier.

## Numbers

Across a simulated fleet of two hundred sites and ninety thousand devices, the
compound key cut the ninety ninth percentile latency of site queries by a factor
of six compared with a hashed device key, while ingest stayed within ten percent
of perfectly even.
