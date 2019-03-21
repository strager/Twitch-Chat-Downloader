import datetime
import json
import os
import re
import sys
from typing import List

import twitch

from app.arguments import Arguments
from app.formatter import Formatter
from app.pipe import Pipe
from app.settings import Settings
from app.logger import Logger, Log


class Downloader:

    def __init__(self):
        self.helix_api = twitch.Helix(client_id=Settings().config['client_id'], use_cache=True)

        self.formats: List[str] = []
        self.whitelist: List[str] = []
        self.blacklist: List[str] = []

        # Populate format list according to whitelist and blacklist
        if 'all' in Arguments().formats and 'all' in Settings().config['formats']:
            self.blacklist = Settings().config['formats']['all']['whitelist'] or []
            self.whitelist = Settings().config['formats']['all']['blacklist'] or []

            # Append formats to list if they can be used
            self.formats = [format_name for format_name in Settings().config['formats'].keys() if
                            self._can_use_format(format_name)]

        else:
            self.formats = [format_name for format_name in Arguments().formats if self._can_use_format(format_name)]

    def _can_use_format(self, format_name: str) -> bool:
        """
        Check if format name should be used based on whitelist and blacklist
        :param format_name: Name of format
        :return: If format should be used
        """

        # Lowercase format name
        format_name = format_name.lower()

        # Reserved format names
        if format_name in ['all']:
            return False

        # Format does not exist
        if format_name not in Settings().config['formats'].keys():
            return False

        # Whitelisted formats
        if self.whitelist and format_name not in self.whitelist:
            return False

        # Blacklisted formats
        if self.blacklist and format_name in self.blacklist:
            return False

        return True

    def video(self, video: twitch.helix.Video) -> None:
        """
        Download chat from video
        :param video: Video object
        :return: None
        """

        # Parse video duration
        regex = re.compile(r'((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?')
        parts = regex.match(video.duration).groupdict()

        time_params = {}
        for name, param in parts.items():
            if param:
                time_params[name] = int(param)

        video_duration = datetime.timedelta(**time_params)

        formatter = Formatter(video)

        # Special case for JSON
        # Build JSON object before writing it
        if 'json' in self.formats:
            output: str = Pipe(Settings().config['formats']['json']['output']).output(video.data)
            os.makedirs(os.path.dirname(output), exist_ok=True)

            data: dict = {
                'video': video.data,
                'comments': []
            }

            for comment in video.comments():
                data['comments'].append(comment.data)
                self.draw_progress(current=comment.content_offset_seconds,
                                   end=video_duration.seconds,
                                   description='json')

            with open(output, 'w') as file:
                json.dump(data, file, indent=4, sort_keys=True)

            Logger().log(f'[json] {output}', Log.PROGRESS)

        # For each format
        for format_name in [x for x in self.formats if x not in ['json']]:
            # Get formatted lines and output file
            comment_tuple, output = formatter.use(format_name)

            os.makedirs(os.path.dirname(output), exist_ok=True)
            with open(output, '+w', encoding='utf-8') as file:
                for line, comment in comment_tuple:
                    if comment:
                        self.draw_progress(current=comment.content_offset_seconds,
                                           end=video_duration.seconds,
                                           description=format_name)

                    file.write(f'{line}')

            Logger().log('[{}] {}'.format(format_name, output), Log.PROGRESS)

    def videos(self, video_ids: List[int]) -> None:
        """
        Download multiple video ids
        :param video_ids: List of video ids
        :return: None
        """
        for video in self.helix_api.videos(video_ids):
            Logger().log(format('\n{}'.format(video.title)), Log.REGULAR)
            self.video(video)

    def channels(self, channels: List[str]) -> None:
        """
        Download videos from multiple channels
        :param channels: List of channel names
        :return: None
        """
        for channel, videos in self.helix_api.users(channels).videos(first=Arguments().first):
            Logger().log(format('\n{}'.format(channel.display_name)), Log.REGULAR)
            for video in videos:
                Logger().log(format('\n{}'.format(video.title)), Log.REGULAR)
                self.video(video)

    @staticmethod
    def draw_progress(current: float, end: float, description: str = 'Downloading') -> None:
        """
        Draw download progress
        :param current: Current chat position (seconds)
        :param end: End position (seconds)
        :param description: Progress description
        :return:
        """
        # Check if progress should be drawn
        if Logger().should_print(Log.PROGRESS):
            sys.stdout.write('[{}] {}%\r'.format(description, '%.2f' % min(current * 10 / end * 10, 100.00)))
            sys.stdout.flush()
