// Small GPX / TCX / FIT activities shared by the tests.
import { Encoder, Profile } from "@garmin/fitsdk";

export const GPX = `<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
 <metadata><time>2020-05-01T10:00:00Z</time></metadata>
 <trk><name>Lunch &amp; Run</name><type>running</type>
  <trkseg>
   <trkpt lat="42.3600" lon="-71.0600"><ele>10</ele><time>2020-05-01T10:00:00Z</time></trkpt>
   <trkpt lat="42.3610" lon="-71.0600"><ele>15</ele><time>2020-05-01T10:01:00Z</time></trkpt>
   <trkpt lat='42.3620' lon='-71.0600'><ele>12</ele><time>2020-05-01T10:02:00Z</time></trkpt>
  </trkseg>
 </trk>
</gpx>`;

export const TCX = `
<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
 <Activities><Activity Sport="Biking"><Id>2021-07-04T08:30:00Z</Id>
  <Lap StartTime="2021-07-04T08:30:00Z"><TotalTimeSeconds>600</TotalTimeSeconds><DistanceMeters>5000</DistanceMeters>
   <Track>
    <Trackpoint><Time>2021-07-04T08:30:00Z</Time><Position><LatitudeDegrees>51.5</LatitudeDegrees><LongitudeDegrees>-0.12</LongitudeDegrees></Position><AltitudeMeters>20</AltitudeMeters><DistanceMeters>0</DistanceMeters></Trackpoint>
    <Trackpoint><Time>2021-07-04T08:31:00Z</Time><DistanceMeters>10</DistanceMeters></Trackpoint>
    <Trackpoint><Time>2021-07-04T08:32:00Z</Time><Position><LatitudeDegrees>51.51</LatitudeDegrees><LongitudeDegrees>-0.12</LongitudeDegrees></Position><AltitudeMeters>30</AltitudeMeters></Trackpoint>
   </Track>
  </Lap>
 </Activity></Activities>
</TrainingCenterDatabase>`;

export function makeFit(): Uint8Array {
  const enc = new Encoder();
  const start = new Date("2022-03-05T07:00:00Z");
  const semi = (deg: number) => Math.round((deg * 2 ** 31) / 180);
  enc.onMesg(Profile.MesgNum.FILE_ID, { type: "activity", manufacturer: "development", product: 0, timeCreated: start, serialNumber: 1 } as any);
  for (let i = 0; i < 3; i++) {
    enc.onMesg(Profile.MesgNum.RECORD, {
      timestamp: new Date(+start + i * 60_000),
      positionLat: semi(48.85 + i * 0.001),
      positionLong: semi(2.35),
    } as any);
  }
  enc.onMesg(Profile.MesgNum.SESSION, {
    timestamp: new Date(+start + 180_000), startTime: start, sport: "running", subSport: "trail",
    totalDistance: 222.5, totalTimerTime: 120, totalAscent: 7,
  } as any);
  return enc.close();
}
