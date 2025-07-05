import requests
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv('.env')

# User sensitive data
api_key: str = os.getenv('API_KEY')
shared_secret: str = os.getenv('SHARED_SECRET')

BASE_URL: str = 'https://ws.audioscrobbler.com/2.0/'
HEADER = ['#AUDIOSCROBBLER/1.1\n', '#TZ/\n', '#CLIENT/Rockbox ipodvideo $Revision$\n']
HEADER_LEN: int = len(HEADER)

SIMULATE_PATH: str = 'D:\\simulation.log'
IGNORED_PATH: str = 'D:\\ignored.log'
UPDATE_TS_PATH: str = 'D:\\.scrobbler_update.log'

# Default parameters
DEFAULT_FILEPATH: str = 'D:\\.scrobbler.log'
DEFAULT_LOCAL_TZ: str = 'UTC+10'


def ts_to_time(timestamp: int) -> None:
    ''' Converts timestamp to human readable time '''
    dt = datetime.fromtimestamp(timestamp)
    return dt

def timezone_adjust(timestamp: str, timezone: str) -> int:
    ''' Adjusts timestamps to UTC from local timezone '''
    delta_ts = int(timezone[3:]) * 3600
    adjusted_ts = int(timestamp) - delta_ts
    return adjusted_ts

def global_offset(filename: str) -> int:
    '''
    If iPod goes flat, battery will reset the clock, to scrobble songs
    played during this time each timestamp is adjusted by determining
    the difference between the real time in UTC, and the time of iPod

    time: current time in utc timestamp format
    '''
    with open(filename, 'r') as f:
        last_scrobble = f.readlines()[-1]
        file_timestamp = int(last_scrobble.split('\t')[-2])
        global_offset = int(datetime.now().timestamp()) - timezone_adjust(file_timestamp, DEFAULT_LOCAL_TZ)
    return global_offset

def update_ts(filename: str, offset: int) -> None:
    ''' Offsets each timestamp by a given contant value '''
    updated_filename = UPDATE_TS_PATH
    if os.path.exists(updated_filename):
        os.remove(updated_filename)

    with open(updated_filename, 'a') as updated:
        with open(filename, 'r') as f:
            for i, line in enumerate(f):
                if i < HEADER_LEN:
                    updated.write(line)
                    continue
                ts = int(line.split('\t')[-2])
                updated_ts = ts + offset
                updated_line = '\t'.join(line.split('\t')[:-2] + [str(updated_ts), '\n'])
                updated.write(updated_line)

def fix_file(filename: str) -> None:
    ''' Adjusts each timestamp in a specifed file, based on timezone and required offset '''
    offset = global_offset(filename)
    update_ts(filename, offset)


class LastFM:
    def __init__(
        self,
        username: str,
        password: str,
        filename: str,
        local_tz: str,
    ) -> None:
        self._username = username
        self._password = password
        self._filename = filename
        self._local_tz = local_tz
        self._sk = None
        self._ignored = []

    def get_username(self) -> str:
        return self._username

    def get_filename(self) -> str:
        ''' Returns path of users .scrobble.log file '''
        return self._filename

    def get_local_tz(self) -> str:
        ''' Returns timezone used by user '''
        return self._local_tz

    def set_filename(self, filename: str) -> None:
        ''' Sets filepath of users .scrobble.log file '''
        self._filename = filename

    def set_local_tz(self, timezone: str) -> None:
        ''' Sets users local timezone '''
        self._local_tz = timezone

    def get_ignored(self) -> list[dict]:
        ''' Returns ignored log '''
        return self._ignored
    
    def set_mobile_sk(self, sk: str) -> None:
        self._sk = sk

    def clear_ignored(self) -> None:
        ''' Deletes ignored log '''
        if os.path.exists(IGNORED_PATH):
            os.remove(IGNORED_PATH)
        self._ignored = []

    def clear_simulate(self) -> None:
        ''' Deletes simulation log file '''
        if os.path.exists(SIMULATE_PATH):
            os.remove(SIMULATE_PATH)

    def generate_signature(self, params: dict) -> str:
        '''
        Generate an api signiture using call parameters to make
        authenticated api calls.
        '''
        keys = sorted(params.keys())
        string_to_hash = ''.join(f"{key}{params[key]}" for key in keys)
        string_to_hash += shared_secret
        return hashlib.md5(string_to_hash.encode('utf-8')).hexdigest()

    def get_mobile_sk(self):
        '''
        Create a web service session for a user.
        Used for authenticating a user when the password
        can be inputted by the user.
        '''
        params = {
            'method': 'auth.getMobileSession',
            'username': self._username,
            'password': self._password,
            'api_key': api_key,
        }
        params['api_sig'] = self.generate_signature(params)
        params['format'] = 'json'
        response = requests.post(BASE_URL, data=params)
        data = response.json()
        if 'session' in data:
            self._sk = data['session']['key']
            return self._sk
        else:
            return
            #raise Exception(f"Error getting session: {data}")  # FIX

    def save_ignored(self) -> None:
        ''' Appends all ignored lines to IGNORED_PATH '''
        with open(IGNORED_PATH, 'a') as ignored:
            for line in self.get_ignored():
                ignored.write(line)

    def readfile(self) -> tuple[list[dict], int]:
        ''' 
        Reads log file, skipped tracks (if any) are appended
        to ignored track list. All other tracks are added into
        groups of length 50. 
        '''
        self.clear_ignored()
        scrobble_groups = []
        scrobble_count = 0
        group = {}

        with open(self.get_filename(), 'r') as f:
            for i, line in enumerate(f):

                # Skip header lines
                if i < HEADER_LEN:
                    continue
                info = line.split('\t')

                # Ignore line if user skipped track
                if info[5] == 'S':
                    self.get_ignored().append(line)
                    continue

                scrobble_count += 1
                element = (scrobble_count - 1) % 50
                ts = timezone_adjust(info[6], self.get_local_tz())

                # Adds track to group with linked information
                group.update({
                    f"artist[{element}]": info[0],
                    f"album[{element}]": info[1],
                    f"track[{element}]": info[2],
                    f"trackNumber[{element}]": info[3],
                    f"duration[{element}]": info[4],
                    f"timestamp[{element}]": ts,
                })
                if element == 49:
                    scrobble_groups.append(group.copy())
                    group = {}

            self.save_ignored()
            scrobble_groups.append(group.copy())
        return scrobble_groups, scrobble_count


    def simulate(self) -> None:
        '''
        Simulates how the tracks would be scrobbled locally, with
        artist, album, track, trackNumber, duration, and local time.
        '''
        self.clear_simulate()
        self.clear_ignored()
        
        with open (SIMULATE_PATH, 'a') as simulation:
            with open(self.get_filename(), 'r') as f:
                for i, line in enumerate(f):

                    # Skip header lines
                    if i < HEADER_LEN:
                        continue
                    info = line.split('\t')

                    # Ignore line if user skipped track
                    if info[5] == 'S':
                        self.get_ignored().append(line)
                        continue

                    # Converts timestamp to local timezone
                    ts = timezone_adjust(info[6], self.get_local_tz())
                    dt = ts_to_time(ts)

                    # Updates line with local time instead of timestamp
                    new_line = '\t'.join([info[0], info[2], str(dt)]) + '\n'
                    simulation.write(new_line)
                self.save_ignored()

    def scrobble_progress(self, progress: int, total_song_count: int) -> None:
        print(f"{round(100 * (progress / total_song_count), 2)}% Scrobbled")

    def scrobble(self) -> None:
        '''
        Scrobbles all non-ignored tracks onto the users
        Last.FM account.
        '''
        # Creates song groups, and calls api to scrobble groups
        song_groups, scrobble_num = self.readfile()
        
        for i, group in enumerate(song_groups):
            params = group.copy()
            params.update({
                'method': 'track.scrobble',
                'api_key': api_key,
                'sk': self._sk,
            })
            params['api_sig'] = self.generate_signature(params)
            response = requests.post(BASE_URL, data=params)

            # Prints response from API
            print(f"Group {i + 1}: {response}")

            progress = i * 50 + len(group)/6
            self.scrobble_progress(progress, scrobble_num)

        # Prints number of tracks scrobbled and ignored
        number_scrobbled = (len(song_groups) - 1) * 50 + int(len(song_groups[-1])/6)
        number_ignored = len(self.get_ignored())
        print(f"Tracks Scrobbled: {number_scrobbled}\n" + \
              f"Tracks Ignored: {number_ignored}")

    def verify(self) -> None:
        '''
        Verifies file timestamp integrity.

        Example:
            If a track has a timestamp less than that of
            a track logged before, an error has occured.
        '''
        ts = float('-inf')
        with open(self.get_filename(), 'r') as f:
            for i, line in enumerate(f):
                if i < HEADER_LEN:
                    continue
                prev = ts
                ts = int(line.split('\t')[-2])
                if prev > ts:
                    print(f"Error detected: Line {i + 1}\n{line}") # FIX CLARITY
                    return
            print('No errors detected')

    def clear_scrobble_log(self) -> None:
        ''' Clears .scrobbler.log to original state with Header '''
        with open(DEFAULT_FILEPATH, 'w') as file:
            file.writelines(HEADER)

# CONFIGURE
# promt a delete, keep, or backup screen after scrobble
#option to view log of ignored songs
