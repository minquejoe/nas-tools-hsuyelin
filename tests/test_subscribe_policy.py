# -*- coding: utf-8 -*-
"""
订阅"只追新不补旧"策略与下载集数空列表处理的测试

背景：用户看完一集就删除一集时，媒体库里缺失的旧集并不代表还要重新下载；
并且"缺失集列表为空"曾被误当成"整季都缺失"，导致把已经看过的整季全部重新下载。
"""
import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.downloader import downloader as downloader_module
from app.downloader.downloader import Downloader
from app.helper import DbHelper
from app.subscribe import Subscribe, RSS_NEW_EPISODE_DAYS
from app.utils.types import MediaType, SearchType


def _days_ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def _days_later(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def _raw_class(factory):
    """
    取出 @singleton 装饰器背后被包装的原始类，测试时可以直接 __new__ 出实例而不触发完整初始化
    """
    for cell in getattr(factory, "__closure__", None) or []:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, type):
            return value
    return factory


class _FakeDbHelper:
    def __init__(self, history=None):
        self._history = history or []

    def get_transfer_history_episodes(self, tmdbid=None, title=None, season=None):
        return list(self._history)


class _FakeMedia:
    def __init__(self, air_dates=None):
        self._air_dates = air_dates or {}

    def get_tmdb_season_episodes(self, tmdbid=None, season=1):
        return [{"episode_number": ep, "air_date": air} for ep, air in self._air_dates.items()]


def _make_subscribe(history=None, air_dates=None):
    raw_class = _raw_class(Subscribe)
    subscribe = raw_class.__new__(raw_class)
    subscribe.dbhelper = _FakeDbHelper(history=history)
    subscribe.media = _FakeMedia(air_dates=air_dates)
    return subscribe


class SubscribeNewEpisodePolicyTest(TestCase):
    def test_old_missing_episodes_are_not_downloaded_again(self):
        """
        看完即删的旧集不补下：进度取媒体库现存集与转移历史，只有更新的集才会下载
        """
        # 媒体库缺失 1-9、12、13（10、11已在库中，1-9、12、13曾经下载并看过删除）
        library_no_exists = {
            296101: [{"season": 1, "episodes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13], "total_episodes": 13}]
        }
        air_dates = {ep: _days_ago(70 - ep * 7) for ep in range(1, 12)}
        air_dates[12] = _days_later(1)
        air_dates[13] = _days_later(8)
        subscribe = _make_subscribe(history=list(range(1, 12)), air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=296101,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=13)
        # 只追更第12、13集，已经看过并删除的旧集不再补下
        self.assertEqual([12, 13], episodes)

    def test_finished_show_downloads_nothing(self):
        """
        已经追完的剧集（全部集都处理过）不会再补下任何集
        """
        library_no_exists = {314554: [{"season": 1, "episodes": list(range(1, 13)), "total_episodes": 12}]}
        air_dates = {ep: _days_ago(60 - ep * 7) for ep in range(1, 13)}
        subscribe = _make_subscribe(history=list(range(1, 13)), air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=314554,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=12)
        self.assertEqual([], episodes)

    def test_long_ago_aired_episodes_are_skipped(self):
        """
        媒体库没有、也从未下载过，但播出时间很久远的旧集不补下（新订阅只跟最近播出的集）
        """
        # 库里只有第1-4集，其余21集都缺失；但只有第5集是最近播出的
        library_no_exists = {210: [{"season": 1, "episodes": list(range(5, 26)), "total_episodes": 25}]}
        air_dates = {1: _days_ago(400), 2: _days_ago(393), 3: _days_ago(386), 4: _days_ago(379),
                     5: _days_ago(2)}
        air_dates.update({ep: _days_ago(370 - ep) for ep in range(6, 26)})
        subscribe = _make_subscribe(history=[], air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=210,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=25)
        self.assertEqual([5], episodes)

    def test_all_missing_season_with_unknown_air_date(self):
        """
        整季缺失（all_missing标记）且播出日期未知时按需要处理，不会漏集
        """
        library_no_exists = {999: [{"season": 1, "episodes": [], "total_episodes": 3, "all_missing": True}]}
        subscribe = _make_subscribe(history=[], air_dates={})
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=999,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=3)
        self.assertEqual([1, 2, 3], episodes)

    def test_current_episode_setting_is_respected(self):
        """
        订阅设置了开始集数时，比它更早的集不再下载
        """
        # 库里只有第1-12集，订阅设置从第13集开始追
        library_no_exists = {268: [{"season": 1, "episodes": list(range(13, 26)), "total_episodes": 25}]}
        air_dates = {ep: _days_ago(max(0, 20 - ep)) for ep in range(1, 26)}
        subscribe = _make_subscribe(history=[], air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=268,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=25,
                                                             current_ep=13)
        self.assertEqual(list(range(13, 26)), episodes)

    def test_recent_episode_window(self):
        """
        恰好超过追新窗口的旧集不再下载，窗口内的仍会下载
        """
        inside = _days_ago(RSS_NEW_EPISODE_DAYS - 1)
        outside = _days_ago(RSS_NEW_EPISODE_DAYS + 1)
        library_no_exists = {1: [{"season": 1, "episodes": [1, 2], "total_episodes": 2}]}
        subscribe = _make_subscribe(history=[], air_dates={1: outside, 2: inside})
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=1,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=2)
        self.assertEqual([2], episodes)


    def test_inflated_total_uses_library_episode_count(self):
        """
        订阅的TOTAL被Bangumi等放大（13集的剧记成25集）时，进度必须按媒体库检查结果的实际集数计算，
        否则会算成"14-25集都已处理"，新集永远不会被追更
        """
        library_no_exists = {
            296101: [{"season": 1, "episodes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13], "total_episodes": 13}]
        }
        air_dates = {ep: _days_ago(70 - ep * 7) for ep in range(1, 12)}
        air_dates[12] = _days_later(1)
        air_dates[13] = _days_later(8)
        subscribe = _make_subscribe(history=list(range(1, 12)), air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=296101,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=25)
        self.assertEqual([12, 13], episodes)

    def test_unknown_air_date_inherits_previous_episode_date(self):
        """
        老剧尾集没有播出日期时，按上一集+7天推算，不能被当成新集重新下载
        """
        library_no_exists = {259140: [{"season": 1, "episodes": list(range(13, 26)), "total_episodes": 25}]}
        air_dates = {ep: _days_ago(500 - ep) for ep in range(1, 25)}  # 第25集没有日期
        subscribe = _make_subscribe(history=list(range(1, 13)), air_dates=air_dates)
        episodes = subscribe.get_subscribe_download_episodes(tmdbid=259140,
                                                             season=1,
                                                             library_no_exists=library_no_exists,
                                                             total_ep=25)
        self.assertEqual([], episodes)


class _FakeRow:
    """模拟SQLAlchemy的Row：支持下标访问但不是tuple子类"""

    def __init__(self, values):
        self._values = values

    def __getitem__(self, index):
        return self._values[index]

    def __iter__(self):
        return iter(self._values)


class _FakeQuery:
    """模拟SQLAlchemy查询：带filter的查询返回空（模拟按TMDBID查不到）"""

    def __init__(self, rows, filtered=False):
        self._rows = rows
        self._filtered = filtered

    def filter(self, *args, **kwargs):
        return _FakeQuery([], True)

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *columns):
        return _FakeQuery(self._rows)


class TransferHistoryLookupTest(TestCase):
    """
    同一部剧因译名变化导致TMDBID不同时，仍能按名称相似度找到转移历史（避免重复补下旧集）
    """

    def _make_helper(self, rows):
        helper = DbHelper.__new__(DbHelper)
        helper._db = _FakeDb(rows)
        return helper

    def test_similar_title_fallback(self):
        helper = self._make_helper([
            _FakeRow(("305814", "与奔驰于透明之夜的你，谈一场看不见的恋爱。", "S01 E11")),
            _FakeRow(("305814", "与奔驰于透明之夜的你，谈一场看不见的恋爱。", "S01 E10")),
            _FakeRow(("305814", "与奔驰于透明之夜的你，谈一场看不见的恋爱。", "S02 E01")),
            _FakeRow(("123456", "完全不相干的另一部剧", "S01 E05")),
        ])
        episodes = helper.get_transfer_history_episodes(
            tmdbid=309974, title="与奔跑在透明之夜的你，谈一场看不见的恋爱。", season=1)
        self.assertEqual([10, 11], episodes)

    def test_unrelated_title_is_not_matched(self):
        helper = self._make_helper([
            _FakeRow(("123456", "碧蓝之海", "S01 E05")),
            _FakeRow(("123456", "碧蓝之海", "S01 E06")),
        ])
        episodes = helper.get_transfer_history_episodes(
            tmdbid=999999, title="碧蓝航线", season=1)
        self.assertEqual([], episodes)


class _FakeTorrentItem:
    """模拟已识别的种子媒体信息"""

    def __init__(self, tmdb_id, episodes, season=1):
        self.tmdb_id = tmdb_id
        self.type = MediaType.TV
        self.enclosure = "http://example.com/a.torrent"
        self.page_url = "http://example.com/a"
        self.title = "Test Show"
        self.org_string = "Test Show S01"
        self._episodes = episodes
        self._season = season
        self.save_path = None
        self.download_setting = None

    def get_season_list(self):
        return [self._season]

    def get_episode_list(self):
        return list(self._episodes)


class _FakeTorrent:
    def __init__(self, items=None):
        self._items = items or []

    def get_download_list(self, media_list, download_order):
        return list(media_list)


class BatchDownloadEmptyEpisodesTest(TestCase):
    """
    "缺失集列表为空"必须表示没有需要下载的集，不能当成整季缺失
    """

    def _make_downloader(self):
        raw_class = _raw_class(Downloader)
        downloader = raw_class.__new__(raw_class)
        downloader._download_order = "site"
        return downloader

    def test_empty_episodes_downloads_nothing(self):
        item = _FakeTorrentItem(tmdb_id=100, episodes=list(range(1, 13)))
        downloader = self._make_downloader()
        calls = []
        with patch.object(downloader_module, "Torrent", lambda: _FakeTorrent([item])), \
                patch.object(downloader, "download", lambda **kwargs: calls.append(kwargs) or ("1", "hash", "")):
            download_items, left = downloader.batch_download(
                in_from=SearchType.RSS,
                media_list=[item],
                need_tvs={100: [{"season": 1, "episodes": [], "total_episodes": 12}]})
        self.assertEqual([], calls, "缺失集为空时不应下载任何集")
        self.assertEqual([], download_items)

    def test_all_missing_season_is_still_downloadable(self):
        item = _FakeTorrentItem(tmdb_id=100, episodes=list(range(1, 13)))
        downloader = self._make_downloader()
        calls = []
        with patch.object(downloader_module, "Torrent", lambda: _FakeTorrent([item])), \
                patch.object(downloader, "download", lambda **kwargs: calls.append(kwargs) or ("1", "hash", "")):
            download_items, left = downloader.batch_download(
                in_from=SearchType.RSS,
                media_list=[item],
                need_tvs={100: [{"season": 1, "episodes": [], "total_episodes": 12, "all_missing": True}]})
        self.assertEqual(1, len(calls), "整季缺失（all_missing）时仍应下载")
        self.assertTrue(download_items)
