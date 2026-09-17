# -*- coding: utf-8 -*-
"""
媒体服务器集数查询测试

覆盖场景：同一部剧集在媒体服务器中存在多个同名条目（比如同时被多个媒体库或
同一媒体库的多个路径包含）时，已存在于其它条目中的集数不能被误判为缺失，
否则订阅会反复重新下载已经整理过的剧集，导致下载目录中残留重复文件。
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.mediaserver.client import emby as emby_module
from app.mediaserver.client import jellyfin as jellyfin_module
from app.mediaserver.client.emby import Emby
from app.mediaserver.client.jellyfin import Jellyfin


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeMediaServer:
    """
    模拟媒体服务器的 Items 查询、Items/{id} 详情及 Shows/{id}/Episodes 接口
    :param series: 剧集条目清单，每项包含 Id、Name、ProductionYear、Tmdb
    :param episodes: {剧集ID: [集号]} 或 {剧集ID: {季号: [集号]}}
    """

    def __init__(self, series, episodes, fail_search=False):
        self.series = series
        self.episodes = episodes
        self.fail_search = fail_search
        self.episode_calls = []

    @staticmethod
    def __get_param(url, name, default=None):
        for part in url.split("?")[-1].split("&"):
            if part.startswith(f"{name}="):
                return part.split("=", 1)[1]
        return default

    def get_res(self, url, *args, **kwargs):
        # 查询某个剧集的所有集
        if "/Episodes" in url:
            series_id = url.split("/Shows/", 1)[1].split("/", 1)[0]
            self.episode_calls.append(series_id)
            season = self.__get_param(url, "season") or self.__get_param(url, "Season") or ""
            episodes = self.episodes.get(series_id) or {}
            if isinstance(episodes, dict):
                episodes = episodes.get(str(season)) or []
            return _FakeResponse({
                "Items": [{
                    "ParentIndexNumber": int(season or 1),
                    "IndexNumber": episode
                } for episode in episodes]
            })
        # 查询某个剧集的详情（校验TMDBID）
        if "/Items/" in url:
            series_id = url.split("/Items/", 1)[1].split("?", 1)[0].split("/", 1)[0]
            for item in self.series:
                if item.get("Id") == series_id:
                    return _FakeResponse({"ProviderIds": {"Tmdb": item.get("Tmdb")}})
            return _FakeResponse({}, status_code=404)
        # 按名称搜索剧集
        if self.fail_search:
            return None
        return _FakeResponse({"Items": self.series})


def _make_client(client_class):
    client = client_class.__new__(client_class)
    client._host = "http://media.local/"
    client._apikey = "key"
    client._user = "user"
    return client


def _make_meta_info(title="Grow Up Show ～向日葵马戏团～", year="2026", tmdb_id="296101"):
    return SimpleNamespace(title=title, year=year, tmdb_id=tmdb_id)


class MediaServerEpisodesTest(TestCase):
    # 同一部剧集在媒体服务器中的两个同名条目，分别只有部分集
    __duplicated_series = [
        {"Id": "old-library", "Name": "Grow Up Show ～向日葵马戏团～", "ProductionYear": 2026, "Tmdb": None},
        {"Id": "new-library", "Name": "Grow Up Show ～向日葵马戏团～", "ProductionYear": 2026, "Tmdb": None}
    ]
    __duplicated_episodes = {"old-library": [10], "new-library": [11]}

    def test_jellyfin_merge_duplicated_series(self):
        """
        Jellyfin中同名剧集条目应合并集数，两个条目中的集都不能被判为缺失
        """
        server = _FakeMediaServer(series=self.__duplicated_series, episodes=self.__duplicated_episodes)
        client = _make_client(Jellyfin)
        with patch.object(jellyfin_module, "RequestUtils", lambda *args, **kwargs: server):
            episodes = client.get_tv_episodes(title="Grow Up Show ～向日葵马戏团～",
                                              year="2026",
                                              tmdb_id="296101",
                                              season=1)
            self.assertEqual({10, 11}, {episode.get("episode_num") for episode in episodes})
            # 共有13集时，只缺失真正没有的集，已存在的第10、11集不再被判为缺失
            no_exists = client.get_no_exists_episodes(_make_meta_info(), 1, 13)
            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13], sorted(no_exists))
        self.assertEqual(["old-library", "new-library"], server.episode_calls[:2])

    def test_emby_merge_duplicated_series(self):
        """
        Emby中同名剧集条目应合并集数
        """
        server = _FakeMediaServer(series=self.__duplicated_series, episodes=self.__duplicated_episodes)
        client = _make_client(Emby)
        with patch.object(emby_module, "RequestUtils", lambda *args, **kwargs: server):
            episodes = client.get_tv_episodes(title="Grow Up Show ～向日葵马戏团～",
                                              year="2026",
                                              tmdb_id="296101",
                                              season=1)
            self.assertEqual({10, 11}, {episode.get("episode_num") for episode in episodes})
            no_exists = client.get_no_exists_episodes(_make_meta_info(), 1, 13)
            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13], sorted(no_exists))

    def test_jellyfin_ignore_series_with_other_tmdbid(self):
        """
        同名但TMDBID不一致的条目应被忽略，避免把其它剧集的集数当成已存在
        """
        server = _FakeMediaServer(
            series=[
                {"Id": "other-show", "Name": "Grow Up Show ～向日葵马戏团～", "ProductionYear": 2026,
                 "Tmdb": "999999"},
                {"Id": "matched-show", "Name": "Grow Up Show ～向日葵马戏团～", "ProductionYear": 2026,
                 "Tmdb": "296101"}
            ],
            episodes={"other-show": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], "matched-show": [11]})
        client = _make_client(Jellyfin)
        with patch.object(jellyfin_module, "RequestUtils", lambda *args, **kwargs: server):
            no_exists = client.get_no_exists_episodes(_make_meta_info(), 1, 13)
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13], sorted(no_exists))
        self.assertEqual(["matched-show"], server.episode_calls)

    def test_jellyfin_series_not_found(self):
        """
        媒体服务器中不存在该剧集时，返回空列表，所有集都算缺失
        """
        server = _FakeMediaServer(series=[], episodes={})
        client = _make_client(Jellyfin)
        with patch.object(jellyfin_module, "RequestUtils", lambda *args, **kwargs: server):
            no_exists = client.get_no_exists_episodes(_make_meta_info(), 1, 3)
            self.assertEqual([1, 2, 3], sorted(no_exists))

    def test_jellyfin_search_failed(self):
        """
        连不上媒体服务器时返回None，由调用方回退到文件目录方式检查
        """
        server = _FakeMediaServer(series=[], episodes={}, fail_search=True)
        client = _make_client(Jellyfin)
        with patch.object(jellyfin_module, "RequestUtils", lambda *args, **kwargs: server):
            self.assertIsNone(client.get_no_exists_episodes(_make_meta_info(), 1, 3))
