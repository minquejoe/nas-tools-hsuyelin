from datetime import datetime
from functools import lru_cache
from urllib.parse import quote

import regex as re
import requests

from app.utils import RequestUtils, StringUtils
from app.utils.types import MediaType


class Bangumi(object):
    """
    https://bangumi.github.io/api/
    """

    _urls = {
        "calendar": "calendar",
        "detail": "v0/subjects/%s",
        "search": "search/subject/%s",
    }
    _base_url = "https://api.bgm.tv/"
    _req = RequestUtils(session=requests.Session())
    _page_num = 30
    # 最近一次search_and_match的匹配得分，供调用方判断匹配可信度
    last_match_score = 0

    def __init__(self):
        pass

    @classmethod
    @lru_cache(maxsize=128)
    def __invoke(cls, url, **kwargs):
        req_url = cls._base_url + url
        params = {}
        if kwargs:
            params.update(kwargs)
        resp = cls._req.get_res(url=req_url, params=params)
        return resp.json() if resp else None

    def calendar(self):
        """
        获取每日放送
        """
        return self.__invoke(self._urls["calendar"], _ts=datetime.strftime(datetime.now(), '%Y%m%d'))

    def detail(self, bid):
        """
        获取番剧详情
        """
        return self.__invoke(self._urls["detail"] % bid, _ts=datetime.strftime(datetime.now(), '%Y%m%d'))

    def search_subjects(self, keyword, type_id=2, limit=10):
        """
        按关键字搜索番剧条目
        :param keyword: 关键字，支持中文名、日文名、罗马音
        :param type_id: 条目类型，2为动画
        :param limit: 返回条数
        :return: 条目列表，每条含 id/name/name_cn/air_date/images 等
        """
        if not keyword:
            return []
        res = self.__invoke(self._urls["search"] % quote(str(keyword)),
                            type=type_id,
                            limit=limit,
                            responseGroup="large",
                            _ts=datetime.strftime(datetime.now(), '%Y%m%d%H'))
        if not res:
            return []
        return res.get("list") or []

    @staticmethod
    def get_subject_names(detail):
        """
        提取条目的所有名称：日文名、中文名、别名（罗马音/英文名等）
        """
        if not detail:
            return []
        names = []
        for name in [detail.get("name"), detail.get("name_cn")]:
            if name and name not in names:
                names.append(name)
        infobox = detail.get("infobox") or []
        for info in infobox:
            key = str(info.get("key") or "")
            if key in ("别名", "別名", "中文名", "英文名", "英文别名"):
                value = info.get("value")
                values = []
                if isinstance(value, list):
                    values = [v.get("v") for v in value if isinstance(v, dict) and v.get("v")]
                elif isinstance(value, str):
                    # 分号分隔的多别名
                    values = [v.strip() for v in re.split(r"[;；]", value) if v.strip()]
                for val in values:
                    if val and val not in names:
                        names.append(val)
        return names

    @staticmethod
    def get_subject_total_episodes(detail):
        """
        提取条目的总集数，获取不到时返回0
        优先 total_episodes，其次 eps，最后 infobox 的话数
        """
        if not detail:
            return 0
        for key in ("total_episodes", "eps"):
            try:
                num = int(detail.get(key) or 0)
                if num > 0:
                    return num
            except (TypeError, ValueError):
                continue
        infobox = detail.get("infobox") or []
        for info in infobox:
            if str(info.get("key") or "") == "话数":
                value = info.get("value")
                if isinstance(value, list) and value:
                    value = value[0].get("v") if isinstance(value[0], dict) else None
                try:
                    num = int(str(value).strip())
                    if num > 0:
                        return num
                except (TypeError, ValueError):
                    return 0
        return 0

    @staticmethod
    def gen_search_variants(keyword):
        """
        生成搜索关键词的多种变体，提高Bangumi搜索命中率
        如 "Kuro Neko to Majo no Kyoushitsu" -> ["Kuro Neko to Majo no Kyoushitsu",
                                                  "KuronekotoMajonoKyoushitsu",
                                                  "Kuro Neko", "Kuroneko"]
        """
        variants = []
        keyword = str(keyword).strip()
        if not keyword:
            return variants
        variants.append(keyword)
        nospace = re.sub(r"\s+", "", keyword)
        if nospace and nospace != keyword:
            variants.append(nospace)
        # 前导词组合，截断的长标题往往更容易命中
        tokens = [t for t in re.split(r"[\s:：·]+", keyword) if t]
        if len(tokens) > 1:
            for num in (2, 1):
                if num <= len(tokens):
                    part = " ".join(tokens[:num])
                    if part not in variants:
                        variants.append(part)
                    part_nospace = re.sub(r"\s+", "", part)
                    if part_nospace and part_nospace not in variants:
                        variants.append(part_nospace)
        # 清理无结果的标点
        cleaned = []
        for var in variants:
            var = var.strip(" :：,，.。-—_")
            if var and var not in cleaned:
                cleaned.append(var)
        # 中文繁体转简体再补一组变体
        cn_variants = []
        for var in cleaned:
            var_cn = Bangumi.__norm_cn_name(var)
            if var_cn and var_cn != var and var_cn not in cleaned:
                cn_variants.append(var_cn)
        cleaned.extend(cn_variants)
        return cleaned[:8]

    @staticmethod
    def __norm_cn_name(name):
        """
        中文名统一转简体，用于比较（繁简差异：小書痴/小书痴、下剋上/下克上）
        """
        if not name:
            return ""
        try:
            import zhconv
            return zhconv.convert(str(name), "zh-cn")
        except Exception:
            return str(name)

    def search_and_match(self, name, year=None, min_score=60, loose=False):
        """
        按名称搜索番剧条目并匹配最佳条目
        :param name: 名称（中文名、日文名或罗马音）
        :param year: 年份，用于辅助匹配
        :param min_score: 命中所需的最低得分
        :param loose: 宽松模式，低于门槛时返回搜索排序第一的条目
        :return: 匹配的条目详情（含名称、别名、集数等），无匹配返回None
        """
        if not name:
            return None
        candidates = []
        for variant in self.gen_search_variants(name):
            candidates = self.search_subjects(keyword=variant, limit=10)
            if candidates:
                break
        if not candidates:
            return None
        match_name = StringUtils.handler_special_chars(Bangumi.__norm_cn_name(name)).upper()
        match_name_nospace = re.sub(r"\s+", "", match_name)
        best_detail = None
        best_score = 0
        best_eps = 0
        for candidate in candidates[:5]:
            bid = candidate.get("id")
            if not bid:
                continue
            detail = self.detail(bid)
            if not detail:
                continue
            names = self.get_subject_names(detail)
            score = 0
            for subject_name in names:
                cmp_name = StringUtils.handler_special_chars(Bangumi.__norm_cn_name(subject_name)).upper()
                cmp_name_nospace = re.sub(r"\s+", "", cmp_name)
                if not cmp_name:
                    continue
                if cmp_name == match_name or cmp_name_nospace == match_name_nospace:
                    score = 100
                elif match_name_nospace and match_name_nospace in cmp_name_nospace:
                    score = max(score, 80)
                elif cmp_name_nospace and cmp_name_nospace in match_name_nospace:
                    score = max(score, 60)
            # 年份加权
            if score > 0 and year:
                air_date = detail.get("date") or candidate.get("air_date") or ""
                air_year = str(air_date)[:4]
                if air_year == str(year):
                    score += 10
                elif air_year and abs(int(air_year or 0) - int(year)) <= 1:
                    score += 5
            # 同分时优先集数多的条目（正篇优先于外传/特别篇）
            eps = self.get_subject_total_episodes(detail)
            if score > best_score or (score == best_score and eps > best_eps):
                best_score = score
                best_detail = detail
                best_eps = eps
        self.last_match_score = best_score
        if best_detail and best_score >= min_score:
            return best_detail
        if loose and candidates:
            self.last_match_score = 0
            return self.detail(candidates[0].get("id"))
        return None

    def get_total_episodes(self, name, year=None):
        """
        查询番剧的总集数，用于与TMDB交叉验证
        :return: (总集数, 匹配得分)，查询不到返回(0, 0)
        """
        detail = self.search_and_match(name=name, year=year)
        if not detail:
            return 0, 0
        return self.get_subject_total_episodes(detail), self.last_match_score

    @staticmethod
    def __dict_item(item, weekday):
        """
        转换为字典
        """
        bid = item.get("id")
        detail = item.get("url")
        title = item.get("name_cn") or item.get("name")
        air_date = item.get("air_date")
        rating = item.get("rating")
        if rating:
            score = rating.get("score")
        else:
            score = 0
        images = item.get("images")
        if images:
            image = images.get("large")
        else:
            image = ''
        summary = item.get("summary")
        return {
            'id': "BG:%s" % bid,
            'orgid': bid,
            'title': title,
            'year': air_date[:4] if air_date else "",
            'type': 'TV',
            'media_type': MediaType.TV.value,
            'vote': score,
            'image': image,
            'overview': summary,
            'url': detail,
            'weekday': weekday
        }

    def get_bangumi_calendar(self, page=1, week=None):
        """
        获取每日放送
        """
        infos = self.calendar()
        if not infos:
            return []
        start_pos = (int(page) - 1) * self._page_num
        ret_list = []
        pos = 0
        for info in infos:
            weeknum = info.get("weekday", {}).get("id")
            if week and int(weeknum) != int(week):
                continue
            weekday = info.get("weekday", {}).get("cn")
            items = info.get("items")
            for item in items:
                if pos >= start_pos:
                    ret_list.append(self.__dict_item(item, weekday))
                pos += 1
                if pos >= start_pos + self._page_num:
                    break

        return ret_list
