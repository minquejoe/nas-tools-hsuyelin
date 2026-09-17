import unittest

from tests.test_mediaserver_episodes import MediaServerEpisodesTest
from tests.test_metainfo import MetaInfoTest

if __name__ == '__main__':
    suite = unittest.TestSuite()
    # 测试名称识别
    suite.addTest(MetaInfoTest('test_metainfo'))
    # 测试媒体服务器集数查询（同名剧集条目合并）
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(MediaServerEpisodesTest))

    # 运行测试
    runner = unittest.TextTestRunner()
    runner.run(suite)
