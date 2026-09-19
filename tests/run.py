import unittest

from tests.test_mediaserver_episodes import MediaServerEpisodesTest
from tests.test_metainfo import MetaInfoTest
from tests.test_subscribe_policy import BatchDownloadEmptyEpisodesTest, SubscribeNewEpisodePolicyTest

if __name__ == '__main__':
    suite = unittest.TestSuite()
    # 测试名称识别
    suite.addTest(MetaInfoTest('test_metainfo'))
    # 测试媒体服务器集数查询（同名剧集条目合并）
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(MediaServerEpisodesTest))
    # 测试订阅"只追新不补旧"策略与空缺失集处理
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(SubscribeNewEpisodePolicyTest))
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(BatchDownloadEmptyEpisodesTest))

    # 运行测试
    runner = unittest.TextTestRunner()
    runner.run(suite)
