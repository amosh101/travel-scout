-- Catalog expansion: add the 22 intl-swept cities to destinations
-- (2026-10-26, per Sir's go-ahead). Coordinates = primary airports,
-- matching the existing rows' convention.

INSERT INTO destinations
  (id, iata_code, name, country, region, latitude, longitude, timezone, created_at)
VALUES
  -- Asia / Middle East
  (gen_random_uuid(),'DXB','Dubai','United Arab Emirates','asia','25.2532','55.3657','Asia/Dubai',now()),
  (gen_random_uuid(),'AUH','Abu Dhabi','United Arab Emirates','asia','24.4330','54.6511','Asia/Dubai',now()),
  (gen_random_uuid(),'SIN','Singapore','Singapore','asia','1.3644','103.9915','Asia/Singapore',now()),
  (gen_random_uuid(),'HND','Tokyo','Japan','asia','35.5494','139.7798','Asia/Tokyo',now()),
  (gen_random_uuid(),'BKK','Bangkok','Thailand','asia','13.6900','100.7501','Asia/Bangkok',now()),
  (gen_random_uuid(),'HKG','Hong Kong','Hong Kong','asia','22.3080','113.9185','Asia/Hong_Kong',now()),
  (gen_random_uuid(),'PVG','Shanghai','China','asia','31.1443','121.8083','Asia/Shanghai',now()),
  (gen_random_uuid(),'ICN','Seoul','South Korea','asia','37.4602','126.4407','Asia/Seoul',now()),
  -- Africa
  (gen_random_uuid(),'MPM','Maputo','Mozambique','africa','-25.9167','32.5833','Africa/Maputo',now()),
  (gen_random_uuid(),'JNB','Johannesburg','South Africa','africa','-26.1367','28.2411','Africa/Johannesburg',now()),
  (gen_random_uuid(),'CPT','Cape Town','South Africa','africa','-33.9715','18.6021','Africa/Johannesburg',now()),
  (gen_random_uuid(),'RAK','Marrakech','Morocco','africa','31.6069','-8.0363','Africa/Casablanca',now()),
  (gen_random_uuid(),'CAI','Cairo','Egypt','africa','30.1219','31.4056','Africa/Cairo',now()),
  (gen_random_uuid(),'NBO','Nairobi','Kenya','africa','-1.3192','36.9278','Africa/Nairobi',now()),
  -- Europe
  (gen_random_uuid(),'VIE','Vienna','Austria','europe','48.1103','16.5697','Europe/Vienna',now()),
  (gen_random_uuid(),'BER','Berlin','Germany','europe','52.3667','13.5033','Europe/Berlin',now()),
  (gen_random_uuid(),'MUC','Munich','Germany','europe','48.3538','11.7861','Europe/Berlin',now()),
  (gen_random_uuid(),'LIS','Lisbon','Portugal','europe','38.7756','-9.1354','Europe/Lisbon',now()),
  (gen_random_uuid(),'PRG','Prague','Czechia','europe','50.1008','14.2600','Europe/Prague',now()),
  (gen_random_uuid(),'ATH','Athens','Greece','europe','37.9364','23.9445','Europe/Athens',now()),
  (gen_random_uuid(),'CPH','Copenhagen','Denmark','europe','55.6180','12.6560','Europe/Copenhagen',now()),
  (gen_random_uuid(),'BUD','Budapest','Hungary','europe','47.4369','19.2556','Europe/Budapest',now())
ON CONFLICT (iata_code) DO UPDATE
  SET name = EXCLUDED.name,
      country = EXCLUDED.country,
      region = EXCLUDED.region,
      latitude = EXCLUDED.latitude,
      longitude = EXCLUDED.longitude,
      timezone = EXCLUDED.timezone;