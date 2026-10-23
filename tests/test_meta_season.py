# -*- coding: utf-8 -*-
"""
名称/文件名季号识别测试

重点：罗马数字季号（II/III）要识别为第2/3季，否则第二季的集会被当成第一季归档，
订阅（S02）在媒体库里永远找不到自己，导致同一批集被反复重新下载。
"""
from unittest import TestCase

from app.media.meta import MetaInfo


class MetaSeasonTest(TestCase):
    def _check(self, name, season, episode):
        meta = MetaInfo(title=name, filePath="/media/Downloading/" + name)
        self.assertEqual(season, meta.get_season_string(), f"{name} 季号识别错误")
        self.assertEqual(episode, meta.get_episode_string(), f"{name} 集号识别错误")

    def test_roman_numeral_season(self):
        """罗马数字季号：II/III 识别为第2/3季，且不残留在名称中"""
        self._check("[orion origin] Katainaka no Ossan, Kensei ni Naru II [10] [1080p] [H265 AAC] [CHT_JPN].mp4",
                    "S02", "E10")
        self._check("Overlord II - 05 [1080p].mkv", "S02", "E05")
        self._check("Some Show III - 07 [1080p].mkv", "S03", "E07")
        meta = MetaInfo(title="[orion origin] Katainaka no Ossan, Kensei ni Naru II [10] [1080p].mp4",
                        filePath="/media/Downloading/x.mp4")
        self.assertNotIn("Ii", meta.en_name or "")

    def test_explicit_season_not_overridden(self):
        """已有明确季号时，标题里出现的罗马数字不影响季号"""
        self._check("THE.GHOST.IN.THE.SHELL.S01E09.EPISODE.09.BRAIN.DRAIN.ii.1080p.AMZN.WEB-DL.mkv",
                    "S01", "E09")
        self._check("[LoliHouse] Some Show S02 - 03 [1080p].mkv", "S02", "E03")

    def test_chinese_and_english_season_forms(self):
        """第X季 / 2nd Season 等常见写法"""
        self._check("[猎户压制部] 乡下大叔成为剑圣 第二季 / Katainaka no Ossan, Kensei ni Naru II - 01 [1080p].mp4",
                    "S02", "E01")
        self._check("Katainaka no Ossan, Kensei ni Naru 2nd Season - 05 [1080p].mkv", "S02", "E05")

    def test_movie_with_roman_numeral_is_not_season(self):
        """电影标题里的罗马数字且没有集号时，不应识别成季"""
        meta = MetaInfo(title="Rocky II.1979.1080p.BluRay.x264.mkv",
                        filePath="/media/Downloading/Rocky II.1979.1080p.BluRay.x264.mkv")
        self.assertIsNone(meta.begin_season)
