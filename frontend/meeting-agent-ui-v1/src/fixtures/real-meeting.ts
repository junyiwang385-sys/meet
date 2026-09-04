import type { MeetingResultV1 } from '../api/types';

// 真实板端数据(g1:学校上半年总结会,~31min)经 v2→v1 映射器产出,供前端完整预览。
// 由 scratchpad/regen_real_meeting.py 生成,勿手改。
export const realMeetingResult: MeetingResultV1 = {
  "schema_version": "meeting-result.v1",
  "meeting_id": "meeting-real-001",
  "result_revision": 1,
  "language": "zh",
  "duration_ms": 1862276,
  "generated_at": "2026-09-03T06:54:03Z",
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": true,
    "chapters": true,
    "decisions": true,
    "action_items": true,
    "evidence": true,
    "formal_version": false
  },
  "transcript": {
    "complete": true,
    "segment_count": 336,
    "segments": [
      {
        "segment_id": "seg-000000",
        "start_ms": 0,
        "end_ms": 20000,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": null,
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000001",
        "start_ms": 20000,
        "end_ms": 36680,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": null,
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000002",
        "start_ms": 36680,
        "end_ms": 41200,
        "speaker_id": "speaker_5",
        "text": "零零二，我是院长。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000003",
        "start_ms": 41200,
        "end_ms": 41640,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000004",
        "start_ms": 41640,
        "end_ms": 45515,
        "speaker_id": "speaker_0",
        "text": "五，幺二六。我是服务员的啊！你好三我儿宝。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000005",
        "start_ms": 43515,
        "end_ms": 47015,
        "speaker_id": "speaker_3",
        "text": "我是服务员，零二三。我是保卫科。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000006",
        "start_ms": 45015,
        "end_ms": 49265,
        "speaker_id": "speaker_1",
        "text": "零二三，我是招生办。零二四，我是后。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000007",
        "start_ms": 47265,
        "end_ms": 50765,
        "speaker_id": "speaker_2",
        "text": "慢，零二四。我是后勤部。然后我……",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000008",
        "start_ms": 48765,
        "end_ms": 53015,
        "speaker_id": "speaker_4",
        "text": "我是教务主任。嗯行。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000009",
        "start_ms": 51015,
        "end_ms": 61310,
        "speaker_id": "speaker_5",
        "text": "嗯，行。咱们今天把各部门儿叫过来开个咱上半年的总结会议。呃，接下来由咱们这个副院长来主持一下这会。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000010",
        "start_ms": 61310,
        "end_ms": 63230,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000011",
        "start_ms": 63230,
        "end_ms": 68530,
        "speaker_id": "speaker_0",
        "text": "好，现在会议开始了啊。这个上半年因为这个疫",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000012",
        "start_ms": 68530,
        "end_ms": 73230,
        "speaker_id": "unknown",
        "text": "穷的，原不闹腾。学生都是在家上午课。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000013",
        "start_ms": 73230,
        "end_ms": 76050,
        "speaker_id": "speaker_0",
        "text": "各个老师也都。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000014",
        "start_ms": 76050,
        "end_ms": 90690,
        "speaker_id": "unknown",
        "text": "提议说网课的效率不是很好，这个教育主任什么建议或者什么方案。呃，咱们由于上半年啊都是那个在家上的那个网课。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000015",
        "start_ms": 90690,
        "end_ms": 93480,
        "speaker_id": "speaker_4",
        "text": "然后老师，好多。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000016",
        "start_ms": 93480,
        "end_ms": 106860,
        "speaker_id": "unknown",
        "text": "我就是实验什么的，我都进行不下去了。咱们下半年的话肯定是不能说再像上一年一样了。我们毕竟马上就要开学，然后也要新招生。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000017",
        "start_ms": 106860,
        "end_ms": 110350,
        "speaker_id": "speaker_4",
        "text": "呃，现在的话。可能老师就……",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000018",
        "start_ms": 110350,
        "end_ms": 121560,
        "speaker_id": "unknown",
        "text": "这块是不缺的，然后老师的水平都比较高。学生咱们就是呃和张文旦商量一下我们三。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000019",
        "start_ms": 121560,
        "end_ms": 124680,
        "speaker_id": "speaker_4",
        "text": "下一个季度，要招新生。咱们政府的。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000020",
        "start_ms": 124680,
        "end_ms": 128950,
        "speaker_id": "unknown",
        "text": "什么样的？呃，比较是一层嘛。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000021",
        "start_ms": 128950,
        "end_ms": 131790,
        "speaker_id": "speaker_0",
        "text": "咱们这好多人，就是好吃。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000022",
        "start_ms": 131790,
        "end_ms": 140250,
        "speaker_id": "unknown",
        "text": "这个好像就会最难了。可能要听一个什么样的标准，就是我需要跟焦作饭商量一下：自己可以不问下？着人办！",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000023",
        "start_ms": 140250,
        "end_ms": 156775,
        "speaker_id": "speaker_0",
        "text": "这个什么？这个问题先走。这个先说老师上课的问题，老师这方面：上课的问题、考试安排的是什么样的？是以期末考试还是下半年返校来考试呢？是。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000024",
        "start_ms": 154775,
        "end_ms": 158220,
        "speaker_id": "speaker_4",
        "text": "考试是以网络方式为那个。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000025",
        "start_ms": 158220,
        "end_ms": 164370,
        "speaker_id": "unknown",
        "text": "标准上，咱们就是对于一些，就是还有一些比较特别重要的时候。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000026",
        "start_ms": 164370,
        "end_ms": 168200,
        "speaker_id": "speaker_0",
        "text": "就是比如说，高数。下专业课吗？",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000027",
        "start_ms": 168200,
        "end_ms": 172100,
        "speaker_id": "unknown",
        "text": "不，主要是像一些高速、一些呃……一些就是。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000028",
        "start_ms": 172100,
        "end_ms": 182510,
        "speaker_id": "speaker_4",
        "text": "是，比较呃重要的一些科目。咱们是需要那个返校以后的那间考试，因为你像在高考五百。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000029",
        "start_ms": 182510,
        "end_ms": 189450,
        "speaker_id": "unknown",
        "text": "实现很多条件，提高。很多呃学生可以在网大查阅资料了。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000030",
        "start_ms": 189450,
        "end_ms": 193325,
        "speaker_id": "speaker_0",
        "text": "那英语的四六级是怎考？",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000031",
        "start_ms": 191325,
        "end_ms": 199390,
        "speaker_id": "speaker_4",
        "text": "手机是很好，因为手机按照现在不按怎么说吧？它是可以开已经。可以开始就是。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000032",
        "start_ms": 199390,
        "end_ms": 200880,
        "speaker_id": "unknown",
        "text": "好。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000033",
        "start_ms": 200880,
        "end_ms": 212255,
        "speaker_id": "speaker_0",
        "text": "行，这说到学生点儿问题。这是闹疫情？那咱们闹疫情的财务账是怎么弄的呢？是学生的费用怎么退呢？还是目前……",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000034",
        "start_ms": 210255,
        "end_ms": 216005,
        "speaker_id": "speaker_6",
        "text": "咱们学校所收的呃，住宿费。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000035",
        "start_ms": 212505,
        "end_ms": 216700,
        "speaker_id": "speaker_0",
        "text": "要所收的呃住宿费，还有学费。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000036",
        "start_ms": 216700,
        "end_ms": 218160,
        "speaker_id": "unknown",
        "text": "收费。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000037",
        "start_ms": 218160,
        "end_ms": 229825,
        "speaker_id": "speaker_6",
        "text": "嗯，目前只有这个住宿费返还了一半。因为我们交的这一年度，它是从上个、上上的去年的那个上半年就开始交了，交的是年。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000038",
        "start_ms": 227825,
        "end_ms": 231010,
        "speaker_id": "speaker_0",
        "text": "那个上半程就开始交，交的是一一一巡天。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000039",
        "start_ms": 230510,
        "end_ms": 235885,
        "speaker_id": "speaker_6",
        "text": "一学年的，咱们只是把这半、这一个学期的住宿费。",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000040",
        "start_ms": 233885,
        "end_ms": 236470,
        "speaker_id": "speaker_0",
        "text": "记得，猪肚饭。退款了？",
        "chapter_id": "chapter-1",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000041",
        "start_ms": 236470,
        "end_ms": 239550,
        "speaker_id": "unknown",
        "text": "嗯，还有就是因为咱们疫情期间嘛。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000042",
        "start_ms": 239550,
        "end_ms": 244060,
        "speaker_id": "speaker_6",
        "text": "呃，没有学，在学校里。没有用到水和电。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000043",
        "start_ms": 244060,
        "end_ms": 246940,
        "speaker_id": "unknown",
        "text": "咱们在这方面省了很大的成本。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000044",
        "start_ms": 246940,
        "end_ms": 251270,
        "speaker_id": "speaker_0",
        "text": "那在学校疫情期间的上半年，学校。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000045",
        "start_ms": 251270,
        "end_ms": 252230,
        "speaker_id": "unknown",
        "text": "开销大。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000046",
        "start_ms": 252230,
        "end_ms": 260445,
        "speaker_id": "speaker_6",
        "text": "学校的开销主要就是老师们的薪资，还有设备的维修。设备。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000047",
        "start_ms": 258445,
        "end_ms": 261850,
        "speaker_id": "speaker_0",
        "text": "设备维修，设备维修吧。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000048",
        "start_ms": 261850,
        "end_ms": 266420,
        "speaker_id": "unknown",
        "text": "比如说，空调这个更新换代。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000049",
        "start_ms": 266420,
        "end_ms": 269320,
        "speaker_id": "speaker_0",
        "text": "还有咱们这个体育馆内的一些。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000050",
        "start_ms": 269320,
        "end_ms": 280170,
        "speaker_id": "unknown",
        "text": "嗯，设备的更新。还有就是：职工们、教职工们的福利哦！先。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000051",
        "start_ms": 280170,
        "end_ms": 287795,
        "speaker_id": "speaker_0",
        "text": "对，这上半年疫情也没开学。安保部门是怎么安排的呢？裁员了还是怎么着啊！安保部这边儿。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000052",
        "start_ms": 285795,
        "end_ms": 293825,
        "speaker_id": "speaker_3",
        "text": "还是怎么了？他保护这边，确实是裁员啊！裁了一部分人。因为这个裁员的。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000053",
        "start_ms": 291825,
        "end_ms": 296075,
        "speaker_id": "speaker_0",
        "text": "这个，裁员的人都在家歇着吗？嗯。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000054",
        "start_ms": 294075,
        "end_ms": 316940,
        "speaker_id": "speaker_3",
        "text": "嗯，对。裁员、裁员的人就是我们裁掉的这些人，我们是他们再往后干什么？我们是不清楚了。就是还在职的这些人哦！我们是要求他们每天来学校这个值班啊。但是值班同时我们要做好那个消毒杀菌的工作呃：消除防疫。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000055",
        "start_ms": 315820,
        "end_ms": 320520,
        "speaker_id": "speaker_0",
        "text": "这咱们本校的场地，外人租用吧。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000056",
        "start_ms": 319240,
        "end_ms": 347860,
        "speaker_id": "speaker_3",
        "text": "嗯，在这个疫情期间是没有的。呃，这个是马上临近夏季呢？夏季的话，嗯，这个疫情也逐渐趋于平稳。在咱们学校那个篮球场的话也会有大大小、大大小小大概二十场比赛吧。然后做一个比赛的时候在一个比赛的同时我们是除了参赛队员和教练，我们是不允许有观众入场因为。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000057",
        "start_ms": 347860,
        "end_ms": 348990,
        "speaker_id": "unknown",
        "text": "这个还是防止。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000058",
        "start_ms": 348990,
        "end_ms": 353870,
        "speaker_id": "speaker_0",
        "text": "大人们，注意：观众入场一定要做好消毒还有防护。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000059",
        "start_ms": 353260,
        "end_ms": 359090,
        "speaker_id": "speaker_3",
        "text": "对，我我们这儿就是呃不不只允许一小部分人。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000060",
        "start_ms": 359090,
        "end_ms": 359970,
        "speaker_id": "unknown",
        "text": "真，真的。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000061",
        "start_ms": 359970,
        "end_ms": 362870,
        "speaker_id": "speaker_0",
        "text": "啊，然后。对对。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000062",
        "start_ms": 361210,
        "end_ms": 370210,
        "speaker_id": "speaker_3",
        "text": "分机进场。对，对，分机进场然后大概就是三隔、隔三个人做一个就隔三个座位做一个人嘛。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000063",
        "start_ms": 369670,
        "end_ms": 373710,
        "speaker_id": "speaker_0",
        "text": "行，你地方会不会控的太大了？隔三个座位。咱们体育。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000064",
        "start_ms": 373710,
        "end_ms": 377750,
        "speaker_id": "speaker_3",
        "text": "厂能做多少人？平常大概能做两千人左右吧。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000065",
        "start_ms": 376700,
        "end_ms": 380070,
        "speaker_id": "speaker_0",
        "text": "有吗？两千人左右，他们来多少人。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000066",
        "start_ms": 380070,
        "end_ms": 380710,
        "speaker_id": "unknown",
        "text": "一百个人吗？",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000067",
        "start_ms": 380710,
        "end_ms": 383800,
        "speaker_id": "speaker_3",
        "text": "嗯，对。来几百个人？就是一些。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000068",
        "start_ms": 382280,
        "end_ms": 385250,
        "speaker_id": "speaker_6",
        "text": "就是那些，像咱们学生。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000069",
        "start_ms": 385250,
        "end_ms": 390360,
        "speaker_id": "unknown",
        "text": "都会反映，就是他们担心打贸易战了。这个问题。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000070",
        "start_ms": 390360,
        "end_ms": 399160,
        "speaker_id": "speaker_3",
        "text": "你下夏季放暑假的时候，不会有篮球场被占的情况呀。学生们都在家啊！",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000071",
        "start_ms": 397160,
        "end_ms": 403620,
        "speaker_id": "speaker_0",
        "text": "这个让安保部门到时候做好，不让外教学生进入本校就行了。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000072",
        "start_ms": 402030,
        "end_ms": 406350,
        "speaker_id": "speaker_3",
        "text": "对，这叫“”。这个好东西啊！",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000073",
        "start_ms": 406350,
        "end_ms": 411770,
        "speaker_id": "unknown",
        "text": "因为，就是咱们开学嘛。都是……呀！",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000074",
        "start_ms": 411770,
        "end_ms": 419890,
        "speaker_id": "speaker_3",
        "text": "不好准备。开学，开学的话是每个人要去做那个面试者啊！咱们是要给……",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000075",
        "start_ms": 419890,
        "end_ms": 425400,
        "speaker_id": "unknown",
        "text": "那个安保部门，还有这个后勤部的预算呀。还有这个……",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000076",
        "start_ms": 425400,
        "end_ms": 428525,
        "speaker_id": "speaker_0",
        "text": "呃，食堂的、食堂的这个教职工们。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000077",
        "start_ms": 426525,
        "end_ms": 429450,
        "speaker_id": "speaker_6",
        "text": "的，时常的这个教师们。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000078",
        "start_ms": 429450,
        "end_ms": 433250,
        "speaker_id": "unknown",
        "text": "对，小偷税。不知道是只商户？",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000079",
        "start_ms": 433250,
        "end_ms": 439375,
        "speaker_id": "speaker_6",
        "text": "对于，对于上学这个这十年毕业毕业生们。他们反需要拿。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000080",
        "start_ms": 437375,
        "end_ms": 440125,
        "speaker_id": "speaker_4",
        "text": "那个他要拿毕业证。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000081",
        "start_ms": 438125,
        "end_ms": 440530,
        "speaker_id": "speaker_0",
        "text": "那个，他要拿毕业证。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000082",
        "start_ms": 440530,
        "end_ms": 441300,
        "speaker_id": "unknown",
        "text": "翻译成中文。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000083",
        "start_ms": 441300,
        "end_ms": 450700,
        "speaker_id": "speaker_3",
        "text": "就是，只要是进去到学生，我们都要去对他们进行这个监视者的测定。然后隔离一段时间。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000084",
        "start_ms": 450700,
        "end_ms": 462150,
        "speaker_id": "unknown",
        "text": "然后我们教主任就是对学生进行了调查，就是关于就是在一层比较现在还是比较严重的那种不明声管道的。就以这经常要打井儿啊！",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000085",
        "start_ms": 462150,
        "end_ms": 465000,
        "speaker_id": "speaker_4",
        "text": "能够反掉的，等到说安保。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000086",
        "start_ms": 465000,
        "end_ms": 475130,
        "speaker_id": "unknown",
        "text": "和那个，或者说对学生的服务以及呃对学生的一些维护。然后不反着咱们就是要通过游戏的方式把。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000087",
        "start_ms": 475130,
        "end_ms": 489160,
        "speaker_id": "speaker_0",
        "text": "那你们那边教务处管的有没有登记表格之类的？哪个班是武汉呢，或者是被隔离的，或者是现在。咱们已经因为咱。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000088",
        "start_ms": 487830,
        "end_ms": 495700,
        "speaker_id": "speaker_4",
        "text": "咱们已经了，因为咱们学校就是在疫情期间。就是每天都需要十天打卡，然后等到就是三年。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000089",
        "start_ms": 495700,
        "end_ms": 502380,
        "speaker_id": "unknown",
        "text": "我们要是想返校的话，需要提前一周就到位。暑期还要进行打卡吗？",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000090",
        "start_ms": 502380,
        "end_ms": 505700,
        "speaker_id": "speaker_0",
        "text": "需要打卡，打卡方式：一种类型。就是通过。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000091",
        "start_ms": 505700,
        "end_ms": 515010,
        "speaker_id": "unknown",
        "text": "咱们需要自己累，多打几次。单一次的话大概就十十多亿了嘛？",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000092",
        "start_ms": 515010,
        "end_ms": 517830,
        "speaker_id": "speaker_0",
        "text": "每天都要打卡吧。",
        "chapter_id": "chapter-2",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000093",
        "start_ms": 517830,
        "end_ms": 524000,
        "speaker_id": "unknown",
        "text": "一下自己要去的地方，嗯去哪儿些地方接触了。我、我接觸了那。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000094",
        "start_ms": 524000,
        "end_ms": 526930,
        "speaker_id": "speaker_4",
        "text": "呃，这个……现在变化特别大。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000095",
        "start_ms": 526930,
        "end_ms": 533710,
        "speaker_id": "unknown",
        "text": "哦，这个问题到时候给下边的辅导员或者同学代表班长。他们都会。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000096",
        "start_ms": 533710,
        "end_ms": 536670,
        "speaker_id": "speaker_0",
        "text": "对，然后这周就爆表了。然后每天上报。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000097",
        "start_ms": 536670,
        "end_ms": 540990,
        "speaker_id": "unknown",
        "text": "嗯，你看一下。哪个英雄需要处理的？你注意一点啊！",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000098",
        "start_ms": 540990,
        "end_ms": 545250,
        "speaker_id": "speaker_0",
        "text": "然后还有上半年这个食堂问题，是怎么说的？",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000099",
        "start_ms": 545250,
        "end_ms": 545820,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000100",
        "start_ms": 545820,
        "end_ms": 566105,
        "speaker_id": "speaker_2",
        "text": "嗯，因为这个疫情呃我们学校不是没有开学吗？呃，这个食堂这些教职工租的这些地方就空闲下来了。因为，嗯没有人在学校嘛。但是这个卫生啊需要隔一段儿时间去打扫一下，因为要去消毒。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000101",
        "start_ms": 564105,
        "end_ms": 567750,
        "speaker_id": "speaker_1",
        "text": "扫一下，因为是消毒这项吗？呃。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000102",
        "start_ms": 567750,
        "end_ms": 568000,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000103",
        "start_ms": 568000,
        "end_ms": 598000,
        "speaker_id": "speaker_2",
        "text": "消毒。去的话，有人去的话肯定是需要消毒的。就是对呃对是有学校学校里有时候呃要安排人去嗯检检查一下嘛啊所以就需要去咱们那个食堂里面哦食堂里面需要的人不太多但是但是一段时间就需要去打扫一下因为咱们疫情期间学生。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000104",
        "start_ms": 598000,
        "end_ms": 614370,
        "speaker_id": "speaker_2",
        "text": "都不在学校，呃食堂开设的比较那个窗口比较少。嗯对但是有有老师需要去就餐但但是开设的窗口比较少所以咱们学校呃上半年这个食堂的收入。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000105",
        "start_ms": 614310,
        "end_ms": 617350,
        "speaker_id": "speaker_0",
        "text": "有，裁员啊！客观。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000106",
        "start_ms": 616630,
        "end_ms": 621490,
        "speaker_id": "speaker_2",
        "text": "对，有就只开设了三个窗口。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000107",
        "start_ms": 620780,
        "end_ms": 624180,
        "speaker_id": "speaker_0",
        "text": "咱们这个食堂是以什么形式？",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000108",
        "start_ms": 624180,
        "end_ms": 627720,
        "speaker_id": "unknown",
        "text": "人，你是属于他。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000109",
        "start_ms": 627720,
        "end_ms": 634110,
        "speaker_id": "speaker_2",
        "text": "外面承包，外包的吗？对外面承包了咱们。承包咱们食堂那个窗口。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000110",
        "start_ms": 634110,
        "end_ms": 635480,
        "speaker_id": "unknown",
        "text": "那。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000111",
        "start_ms": 635480,
        "end_ms": 647610,
        "speaker_id": "speaker_1",
        "text": "我想问一下：，这承包的这些客户他们是住在学校有专门的宿舍吗？还是他们住在学校外面每天都要进出学校。一",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000113",
        "start_ms": 647630,
        "end_ms": 662210,
        "speaker_id": "speaker_2",
        "text": "因为呃疫情期间不是每天都需要，呃老师们过来过来学校的。就是有一些事情安排的时候嗯就需要来一趟所以，咱们老师是不在学校住的。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000114",
        "start_ms": 660920,
        "end_ms": 673965,
        "speaker_id": "speaker_0",
        "text": "有没有学校住的？食堂都是平房。有，没有那种就是在本地的但是也没有自己的房子也不在外边儿住就属于一城来叫他都会。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000115",
        "start_ms": 671965,
        "end_ms": 674490,
        "speaker_id": "speaker_4",
        "text": "一般在小船多呗。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000116",
        "start_ms": 674490,
        "end_ms": 677480,
        "speaker_id": "unknown",
        "text": "这个，咱们开始。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000117",
        "start_ms": 677480,
        "end_ms": 685250,
        "speaker_id": "speaker_2",
        "text": "都跟老师协商过，呃可以有自愿、自愿想要住在教职工宿舍的也有。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000118",
        "start_ms": 685250,
        "end_ms": 686130,
        "speaker_id": "unknown",
        "text": "也有咱们。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000119",
        "start_ms": 686130,
        "end_ms": 691140,
        "speaker_id": "speaker_0",
        "text": "那他这个教职工宿舍的费用跟学生宿舍的费用。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000120",
        "start_ms": 691140,
        "end_ms": 696600,
        "speaker_id": "unknown",
        "text": "大一大，你像教职工的话呃他们的课业负担。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000121",
        "start_ms": 696600,
        "end_ms": 699790,
        "speaker_id": "speaker_5",
        "text": "哦，上半年咱学校。",
        "chapter_id": "chapter-3",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000122",
        "start_ms": 699790,
        "end_ms": 706420,
        "speaker_id": "unknown",
        "text": "嗯，先说个今天早退了。这一块儿已经退出去了。这一块刚才财务部那边说已经撤。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000123",
        "start_ms": 706420,
        "end_ms": 709180,
        "speaker_id": "speaker_4",
        "text": "对呀，一半儿就直接到一半儿去那个出租房。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000124",
        "start_ms": 708460,
        "end_ms": 711820,
        "speaker_id": "speaker_6",
        "text": "书费。退到一半，书费是不用退的也得。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000125",
        "start_ms": 711820,
        "end_ms": 719120,
        "speaker_id": "unknown",
        "text": "就是逻辑的啊，那种有学费的话也是。补学费也是一样一个在线上他们课是。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000126",
        "start_ms": 719120,
        "end_ms": 725740,
        "speaker_id": "speaker_6",
        "text": "没有少，那个住宿费退一半。对，住宿费用一半是因为他一年住这这些年这一半年。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000127",
        "start_ms": 720995,
        "end_ms": 724495,
        "speaker_id": "speaker_4",
        "text": "对，一块。对不住我了，因为是一块是为他也是这。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000128",
        "start_ms": 725740,
        "end_ms": 729500,
        "speaker_id": "unknown",
        "text": "这个，这半个。嗯，我有一个那个……",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000129",
        "start_ms": 729500,
        "end_ms": 732270,
        "speaker_id": "speaker_3",
        "text": "那学生在这一块有反馈吗？",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000130",
        "start_ms": 732100,
        "end_ms": 738260,
        "speaker_id": "speaker_6",
        "text": "有反面啊！一开始的时候，他们最开始的时候是他们要求的。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000131",
        "start_ms": 737840,
        "end_ms": 740780,
        "speaker_id": "speaker_0",
        "text": "要求要全退。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000132",
        "start_ms": 740780,
        "end_ms": 756200,
        "speaker_id": "unknown",
        "text": "嗯，对。最后我们也就是呃这没什么合情合理的所以一个相互爱帮助的教育是出来的关于这个我也得说：还有就是嗯老师们的心资问题。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000133",
        "start_ms": 756200,
        "end_ms": 761100,
        "speaker_id": "speaker_6",
        "text": "由于，由于这个这半年咱们没有。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000134",
        "start_ms": 761100,
        "end_ms": 761640,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000135",
        "start_ms": 761640,
        "end_ms": 764600,
        "speaker_id": "speaker_0",
        "text": "那个，不用设备。不用这个，不用教室。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000136",
        "start_ms": 764600,
        "end_ms": 765140,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000137",
        "start_ms": 765140,
        "end_ms": 775920,
        "speaker_id": "speaker_6",
        "text": "设备，所以水电省下来很多的经费。咱们可以在嗯用这些经费人加那个增加一些教学质量。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000138",
        "start_ms": 775920,
        "end_ms": 777900,
        "speaker_id": "unknown",
        "text": "嗯，不是叫甄子长啊。就是。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000139",
        "start_ms": 777900,
        "end_ms": 780970,
        "speaker_id": "speaker_3",
        "text": "这没什么，啊或者说是。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000140",
        "start_ms": 780970,
        "end_ms": 800970,
        "speaker_id": "unknown",
        "text": "环境上的一些改变，改变。对但是你像现在咱们的老师他们的任务分为两个一个是授课啊一个是做自己的项目嗯这个方面的话就是项目方面呢是就我们能够也是尽量进行帮助然后在薪资方面吧。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000141",
        "start_ms": 800970,
        "end_ms": 819910,
        "speaker_id": "unknown",
        "text": "就是，晚上教呃晚上教课。老师可能会更加辛苦一些，因为常用电脑。所以说咱们学校的话，呃财务部是可以，就是按就是因为省下来这笔钱可以进行给老师一些嗯帮助吧？就相当于是。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000142",
        "start_ms": 819910,
        "end_ms": 822830,
        "speaker_id": "speaker_3",
        "text": "呃，铁皮。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000143",
        "start_ms": 822830,
        "end_ms": 824330,
        "speaker_id": "unknown",
        "text": "直接知道，对。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000144",
        "start_ms": 824330,
        "end_ms": 827200,
        "speaker_id": "speaker_0",
        "text": "有没有，就是属于那种。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000145",
        "start_ms": 827200,
        "end_ms": 837250,
        "speaker_id": "unknown",
        "text": "之类的，给老师发一些东西。这个是什么？学校的饭局吗？传统的老方对因为咱们学校是唠所以说这有……",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000146",
        "start_ms": 837250,
        "end_ms": 840790,
        "speaker_id": "speaker_0",
        "text": "没有，这个经费。这个后勤部一般都会送一些什么？",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000147",
        "start_ms": 840790,
        "end_ms": 842610,
        "speaker_id": "unknown",
        "text": "嗯。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000148",
        "start_ms": 842610,
        "end_ms": 858100,
        "speaker_id": "speaker_2",
        "text": "嗯，就是像过节的话就会送一些应应节的一些产品就比如月饼啊或者送一些粽子啊然后过年的话会送一些呃油啊这些。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000149",
        "start_ms": 849500,
        "end_ms": 852270,
        "speaker_id": "speaker_1",
        "text": "月饼啊，或者一些粽子啊。",
        "chapter_id": "chapter-4",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000150",
        "start_ms": 858100,
        "end_ms": 861100,
        "speaker_id": "unknown",
        "text": "这些还有饮料啊什么，然后那个。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000151",
        "start_ms": 861100,
        "end_ms": 863950,
        "speaker_id": "speaker_2",
        "text": "呃，教师教职工们都拿回家嘛。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000152",
        "start_ms": 863950,
        "end_ms": 864010,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000153",
        "start_ms": 864010,
        "end_ms": 866770,
        "speaker_id": "speaker_4",
        "text": "你像平时的话，可能教师在。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000154",
        "start_ms": 866770,
        "end_ms": 870130,
        "speaker_id": "unknown",
        "text": "需要就餐的，呃餐点的话也是必须得有。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000155",
        "start_ms": 870130,
        "end_ms": 876570,
        "speaker_id": "speaker_0",
        "text": "那这个学校就餐是属于，充卡里边儿还是直接用微信？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000156",
        "start_ms": 876570,
        "end_ms": 882700,
        "speaker_id": "unknown",
        "text": "现金的话不太好吗？我觉得。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000157",
        "start_ms": 882700,
        "end_ms": 885460,
        "speaker_id": "speaker_1",
        "text": "现在年轻人比较少了，是吧？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000158",
        "start_ms": 885460,
        "end_ms": 897310,
        "speaker_id": "unknown",
        "text": "大部分都是一个方法，一直是用一卡通。因为老师也会配备嗯自己的卡。对，咱学校是属于呃两个方法一个。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000159",
        "start_ms": 897310,
        "end_ms": 900360,
        "speaker_id": "speaker_2",
        "text": "这就是一卡不，教职工和学生都有的。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000160",
        "start_ms": 900360,
        "end_ms": 900810,
        "speaker_id": "unknown",
        "text": "不行。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000161",
        "start_ms": 900810,
        "end_ms": 907420,
        "speaker_id": "speaker_0",
        "text": "然后就是这个，哎呀妈！这个学校。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000162",
        "start_ms": 907420,
        "end_ms": 909480,
        "speaker_id": "unknown",
        "text": "是独立的，一个吧。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000163",
        "start_ms": 909480,
        "end_ms": 939480,
        "speaker_id": "speaker_2",
        "text": "咱们宿舍这方面的话，其实嗯其实是环境是比较好的。呃配备着配都是独立卫生间然后安装着空调啊这一段时间是完善了一下因为设备不是半年都宿舍空闲下来嘛？嗯这如果下半年要要如果下半年要开学的话我建议咱们这边儿是检查一下那些设。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000164",
        "start_ms": 939480,
        "end_ms": 947240,
        "speaker_id": "speaker_2",
        "text": "设备是否有损坏，或者呃放的那些腐坏了电路啊什么。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000165",
        "start_ms": 947240,
        "end_ms": 948470,
        "speaker_id": "unknown",
        "text": "需要去做检查一下。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000166",
        "start_ms": 948470,
        "end_ms": 951890,
        "speaker_id": "speaker_0",
        "text": "然后就是，行。那你直接到时候给财务部报一下。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000167",
        "start_ms": 951890,
        "end_ms": 951960,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000168",
        "start_ms": 951960,
        "end_ms": 956200,
        "speaker_id": "speaker_1",
        "text": "就说到这个下半年，因为上半年一直没有开学。然后",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000169",
        "start_ms": 956200,
        "end_ms": 958810,
        "speaker_id": "unknown",
        "text": "下半年，咱们要迎来新的那个招生。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000170",
        "start_ms": 958810,
        "end_ms": 977235,
        "speaker_id": "speaker_1",
        "text": "然后因为明天现在也高考了嘛，呃九月份会有新的同学啊来我们的学校。然后我现在就觉得是我们应该去财务那里抽一部分钱，然后把大部分放在招生宣传和招生咨询上面。宣传一下我们学校。行这个。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000171",
        "start_ms": 975235,
        "end_ms": 982485,
        "speaker_id": "speaker_0",
        "text": "嗯，行。这个你到时候一个方案就是咱报一下或者现在有什么想法也可以说一说呀？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000172",
        "start_ms": 980485,
        "end_ms": 1009220,
        "speaker_id": "speaker_1",
        "text": "也可以说一下。想法就是先，嗯首先咱们那个宣传海报上一定要：咱们学校的首先是咱们的硬件、硬件设施。因为现在很多其实很多学校并不是说都配有空调。对。咱们学校既然有这个硬件的话就可以先说出来然后就咱们学校的教育，然后各种呃各种细节安全，然后绿化，然后食堂，然后……咱们呢？嗯，这些。首先，咱们学生反映。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000173",
        "start_ms": 1005345,
        "end_ms": 1008095,
        "speaker_id": "speaker_0",
        "text": "咱们呢，对对对这些。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000174",
        "start_ms": 1009220,
        "end_ms": 1012350,
        "speaker_id": "unknown",
        "text": "作业，你自己各种什么条件吧？都是。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000175",
        "start_ms": 1012350,
        "end_ms": 1019050,
        "speaker_id": "speaker_0",
        "text": "比较好的反映。那么有的男生，他比较关心宿舍会不会停电问题或者是能。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000176",
        "start_ms": 1019050,
        "end_ms": 1021820,
        "speaker_id": "unknown",
        "text": "是否使用像电饭煲之类的东西？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000177",
        "start_ms": 1021820,
        "end_ms": 1027945,
        "speaker_id": "speaker_1",
        "text": "这个其实为了安全，还是不建议说在它上这些大功率的电器。对不对？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000178",
        "start_ms": 1025945,
        "end_ms": 1031695,
        "speaker_id": "speaker_2",
        "text": "一些大功率的电器，对不建议使用。为了避免发生一些火。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000179",
        "start_ms": 1027445,
        "end_ms": 1032445,
        "speaker_id": "speaker_4",
        "text": "灾啥的。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000180",
        "start_ms": 1030445,
        "end_ms": 1033945,
        "speaker_id": "speaker_1",
        "text": "发生一些火灾啥的。对，是啊。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000181",
        "start_ms": 1031945,
        "end_ms": 1041445,
        "speaker_id": "speaker_0",
        "text": "那啥呢？对，行。那每栋楼从上面都会放灭火器吗？对你有灭火器嘛？这个每栋楼。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000182",
        "start_ms": 1037195,
        "end_ms": 1039945,
        "speaker_id": "speaker_1",
        "text": "消防，对。你也不用我提醒了。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000183",
        "start_ms": 1039445,
        "end_ms": 1042195,
        "speaker_id": "speaker_3",
        "text": "对，这个每栋楼。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000184",
        "start_ms": 1040195,
        "end_ms": 1046695,
        "speaker_id": "speaker_2",
        "text": "每幢楼层都会放置三个嗯灭火器地点。走到新的一",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000185",
        "start_ms": 1044695,
        "end_ms": 1051195,
        "speaker_id": "speaker_1",
        "text": "灭火器地点。等到新的一批学生开学之后，然后安宝那边会培训那个。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000186",
        "start_ms": 1049195,
        "end_ms": 1053445,
        "speaker_id": "speaker_2",
        "text": "会去那个消防演练。对，安保这边有技术。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000187",
        "start_ms": 1051445,
        "end_ms": 1057945,
        "speaker_id": "speaker_1",
        "text": "对，安保这边要进行消防演练。先看那还能不能使用？",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000188",
        "start_ms": 1055945,
        "end_ms": 1060945,
        "speaker_id": "speaker_4",
        "text": "那我们合作，就是安排学生出行。呃，消防演习这。",
        "chapter_id": "chapter-5",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000189",
        "start_ms": 1058945,
        "end_ms": 1070920,
        "speaker_id": "speaker_0",
        "text": "这个也让教导主任到时候去推广一下咱们学校之类的社团活动啊！也可以拉学生的兴趣或者什么学生部门儿啊组织一下这方面额活动。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000190",
        "start_ms": 1070920,
        "end_ms": 1071150,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000191",
        "start_ms": 1071150,
        "end_ms": 1080970,
        "speaker_id": "speaker_4",
        "text": "那就是，就需要咱们就是进行宣传了。因为每年都会在开学的，就是做完新生以后呢？因为这期完。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000192",
        "start_ms": 1080970,
        "end_ms": 1085180,
        "speaker_id": "unknown",
        "text": "我们举办一些活动，来介绍我们的社团以及学生。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000193",
        "start_ms": 1085180,
        "end_ms": 1087940,
        "speaker_id": "speaker_0",
        "text": "呃，素质。然后咱们可以。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000194",
        "start_ms": 1087940,
        "end_ms": 1099590,
        "speaker_id": "unknown",
        "text": "有很多选择吧，可以进行什么志愿者活动。还有进行就是科科协活动，就是相当于创新创业之类的。他们需要对于这方面有一个很大的。嗯是选。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000195",
        "start_ms": 1099590,
        "end_ms": 1108780,
        "speaker_id": "speaker_1",
        "text": "当然，这些可以把它放在咱们学校的官网上面。对，只有想报考的学生他们：点开网站就能直接获得全面的了解、直观的理解咱们学校。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000196",
        "start_ms": 1108780,
        "end_ms": 1108920,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000197",
        "start_ms": 1108920,
        "end_ms": 1113250,
        "speaker_id": "speaker_0",
        "text": "行，那宣传这方面、财务这边和经济需要。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000198",
        "start_ms": 1113250,
        "end_ms": 1117810,
        "speaker_id": "unknown",
        "text": "啊！不是晚餐，是中午。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000199",
        "start_ms": 1117810,
        "end_ms": 1120650,
        "speaker_id": "speaker_0",
        "text": "经济预算，这东西。他有经济预算。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000200",
        "start_ms": 1120490,
        "end_ms": 1123340,
        "speaker_id": "speaker_6",
        "text": "就是需要各部门。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000201",
        "start_ms": 1123340,
        "end_ms": 1126660,
        "speaker_id": "unknown",
        "text": "嗯，没有一个计划。大概知道多少钱？我给。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000202",
        "start_ms": 1126660,
        "end_ms": 1131820,
        "speaker_id": "speaker_0",
        "text": "哦，主要是招生办这边。他这边调我这块做出来的具体的计划。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000203",
        "start_ms": 1130400,
        "end_ms": 1133200,
        "speaker_id": "speaker_1",
        "text": "就是会。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000204",
        "start_ms": 1133200,
        "end_ms": 1134690,
        "speaker_id": "unknown",
        "text": "是啊，财务这边。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000205",
        "start_ms": 1134690,
        "end_ms": 1137610,
        "speaker_id": "speaker_0",
        "text": "这不算。等他给你报，报呗？对然后我。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000206",
        "start_ms": 1136690,
        "end_ms": 1139540,
        "speaker_id": "speaker_4",
        "text": "们这边收费的话也是像你们今天。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000207",
        "start_ms": 1139540,
        "end_ms": 1140610,
        "speaker_id": "unknown",
        "text": "那个。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000208",
        "start_ms": 1140610,
        "end_ms": 1143530,
        "speaker_id": "speaker_2",
        "text": "像，后勤这边儿的话就是。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000209",
        "start_ms": 1143530,
        "end_ms": 1147400,
        "speaker_id": "unknown",
        "text": "是需要，嗯？需要重新检修一下吧。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000210",
        "start_ms": 1147400,
        "end_ms": 1155900,
        "speaker_id": "speaker_0",
        "text": "他那个校长，屁家里头都塞的宿舍热水忽冷忽热的那种。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000211",
        "start_ms": 1155900,
        "end_ms": 1156090,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000212",
        "start_ms": 1156090,
        "end_ms": 1164025,
        "speaker_id": "speaker_2",
        "text": "这个是呃，宿舍水压的问题。嗯，你这个需要二次加压。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000213",
        "start_ms": 1162025,
        "end_ms": 1165310,
        "speaker_id": "speaker_0",
        "text": "吗？",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000214",
        "start_ms": 1164790,
        "end_ms": 1173300,
        "speaker_id": "speaker_2",
        "text": "嗯，这个、这个是宿舍肯定会出现的问题。这个不是咱们硬件设施的问问题。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000215",
        "start_ms": 1173210,
        "end_ms": 1182055,
        "speaker_id": "speaker_0",
        "text": "那会不会在顶楼的学生，给他们安点太阳能之类的东西？如果顶楼供水它不足的话。这个。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000216",
        "start_ms": 1180055,
        "end_ms": 1191055,
        "speaker_id": "speaker_2",
        "text": "供水它不足的话，这个问题其实呃发生的时间少就。如果太多就是太多、太多人使用的话。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000217",
        "start_ms": 1189055,
        "end_ms": 1191805,
        "speaker_id": "speaker_3",
        "text": "那是高峰期的时候，会出现。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000218",
        "start_ms": 1189805,
        "end_ms": 1194055,
        "speaker_id": "speaker_4",
        "text": "高峰期的时候会出现。因为这个问题是比较少的。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000219",
        "start_ms": 1192055,
        "end_ms": 1194970,
        "speaker_id": "speaker_1",
        "text": "高峰期的时候，可以就。",
        "chapter_id": "chapter-6",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000220",
        "start_ms": 1194970,
        "end_ms": 1198900,
        "speaker_id": "unknown",
        "text": "就是在楼顶上安装一个，为了让学生们使用就更加方便。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000221",
        "start_ms": 1198900,
        "end_ms": 1211110,
        "speaker_id": "speaker_0",
        "text": "行，这个宣传主要还有校园环境吧？咱得用航拍仪航拍一下。这个安保部门儿：，这个还有跟后勤部门儿：，这个怎么处理校园环境啊？这什么地步！",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000222",
        "start_ms": 1211110,
        "end_ms": 1214270,
        "speaker_id": "unknown",
        "text": "大方向之类的，或者什么。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000223",
        "start_ms": 1214270,
        "end_ms": 1231980,
        "speaker_id": "speaker_3",
        "text": "嗯，安保这边儿就是一个是会就定期的对这个校园内的一些设施检查。航拍这边的话，就是咱们有那个专门的无人机，呃，无人机去拍摄要有一个看地哦啊！",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000224",
        "start_ms": 1231980,
        "end_ms": 1235810,
        "speaker_id": "unknown",
        "text": "那许多，许多咨询。咱们学校的学生现在就开始问：因为今年。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000225",
        "start_ms": 1235810,
        "end_ms": 1241170,
        "speaker_id": "speaker_1",
        "text": "疫情原因，然后咱们开学之后这些新生会不会有军训这个问题。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000226",
        "start_ms": 1241170,
        "end_ms": 1242350,
        "speaker_id": "unknown",
        "text": "反问，是不是应该。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000227",
        "start_ms": 1242350,
        "end_ms": 1248475,
        "speaker_id": "speaker_0",
        "text": "我问一下，军训有吗？军事方面肯定是要军训的。这个是重点儿啊！",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000228",
        "start_ms": 1246475,
        "end_ms": 1251475,
        "speaker_id": "speaker_1",
        "text": "那，这人员聚集不会太大吗？我们可以考虑。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000229",
        "start_ms": 1249475,
        "end_ms": 1258320,
        "speaker_id": "speaker_2",
        "text": "一下军训的时间。可以开学之后放在这个学期末，或者……",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000230",
        "start_ms": 1258320,
        "end_ms": 1258700,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000231",
        "start_ms": 1258700,
        "end_ms": 1261500,
        "speaker_id": "speaker_4",
        "text": "是，就将军训的王猛退。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000232",
        "start_ms": 1261500,
        "end_ms": 1263490,
        "speaker_id": "unknown",
        "text": "对呀。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000233",
        "start_ms": 1263490,
        "end_ms": 1267365,
        "speaker_id": "speaker_1",
        "text": "可以直，是吧？就是没有取消。但是是可以直。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000234",
        "start_ms": 1265365,
        "end_ms": 1268600,
        "speaker_id": "speaker_0",
        "text": "但是，推迟。因为是军训这个事国家规定。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000235",
        "start_ms": 1268600,
        "end_ms": 1271230,
        "speaker_id": "unknown",
        "text": "是，必须要参加。好。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000236",
        "start_ms": 1271230,
        "end_ms": 1283355,
        "speaker_id": "speaker_0",
        "text": "那招生办这方面，如果要军训的话有什么新颖的活动之类的？可以吸引学生。他们毕竟有的学生呢比较恐惧军训吧！你像学生。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000237",
        "start_ms": 1281355,
        "end_ms": 1289660,
        "speaker_id": "speaker_4",
        "text": "句型是吧？你像学生，像我反映就是，在军训的时候他们教我们给买西瓜。呃这个行为的话就会特别受。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000238",
        "start_ms": 1289660,
        "end_ms": 1292800,
        "speaker_id": "unknown",
        "text": "我觉得，呃喜爱。然后。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000239",
        "start_ms": 1292800,
        "end_ms": 1295925,
        "speaker_id": "speaker_4",
        "text": "如果学生。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000240",
        "start_ms": 1293925,
        "end_ms": 1305675,
        "speaker_id": "speaker_1",
        "text": "对这方面有反馈，肯定会跟那些教官提前都说好。就是也不要说是为了军训而军训，应该在训练的过程中。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000241",
        "start_ms": 1303675,
        "end_ms": 1310175,
        "speaker_id": "speaker_3",
        "text": "增加一个。就是本来大家都是刚来嘛，在军训过程当中。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000242",
        "start_ms": 1308175,
        "end_ms": 1315425,
        "speaker_id": "speaker_1",
        "text": "对，然后关系更融洽一点。多认识一些朋友、熟悉这个班级、熟悉这个大环境。小王同样也是。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000243",
        "start_ms": 1313425,
        "end_ms": 1317080,
        "speaker_id": "speaker_4",
        "text": "对，小白同样也是军训的目的了。就是为了。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000244",
        "start_ms": 1317080,
        "end_ms": 1323600,
        "speaker_id": "unknown",
        "text": "就是锻炼什么意志。这个方面的话，咱们是必须要做到最好了，因为对于……对于。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000245",
        "start_ms": 1323600,
        "end_ms": 1327020,
        "speaker_id": "speaker_4",
        "text": "学生来说，咱们一个综合素质。其实……",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000246",
        "start_ms": 1327020,
        "end_ms": 1331940,
        "speaker_id": "unknown",
        "text": "居然学车。对于那些刁人呢，咱们也是……",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000247",
        "start_ms": 1331940,
        "end_ms": 1338550,
        "speaker_id": "speaker_4",
        "text": "需要管理的，这就需要咱们招生办的话。可能政策不一样了，就是对于一些条件咱比较有。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000248",
        "start_ms": 1338550,
        "end_ms": 1338830,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000249",
        "start_ms": 1338830,
        "end_ms": 1346950,
        "speaker_id": "speaker_0",
        "text": "不一定。那你这个教授这高教官，是从学校、军校里头招呢？还是从……",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000250",
        "start_ms": 1346950,
        "end_ms": 1352070,
        "speaker_id": "unknown",
        "text": "咱们学校的话，咱们学校的国防生呢话是现在也基本上没有了。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000251",
        "start_ms": 1352070,
        "end_ms": 1354830,
        "speaker_id": "speaker_4",
        "text": "所以说，感觉教官只能是去。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000252",
        "start_ms": 1354830,
        "end_ms": 1355820,
        "speaker_id": "unknown",
        "text": "就是。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000253",
        "start_ms": 1355820,
        "end_ms": 1358945,
        "speaker_id": "speaker_0",
        "text": "城市里的那个外币吧，就是你像。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000254",
        "start_ms": 1356945,
        "end_ms": 1365795,
        "speaker_id": "speaker_4",
        "text": "卖票嘛，就是你像消防、消防队的他们的队员也会，就是作为教官来参加这个。",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000255",
        "start_ms": 1363795,
        "end_ms": 1369600,
        "speaker_id": "speaker_3",
        "text": "嗯，也可以招一些这个当届的退伍兵。啊！",
        "chapter_id": "chapter-7",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000256",
        "start_ms": 1369280,
        "end_ms": 1372405,
        "speaker_id": "speaker_0",
        "text": "有经验的。对，对我比较。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000257",
        "start_ms": 1370405,
        "end_ms": 1376675,
        "speaker_id": "speaker_3",
        "text": "对，退伍兵的话也。他们也有着也愿意吧？",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000258",
        "start_ms": 1374675,
        "end_ms": 1383515,
        "speaker_id": "speaker_4",
        "text": "呢，对你像网上反馈很好的那些什么“帅一些小哥哥”做教班的话。他也是评价不错啊！",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000259",
        "start_ms": 1381515,
        "end_ms": 1389010,
        "speaker_id": "speaker_0",
        "text": "他也是退伍兵。那如果退伍兵会不会，如果年龄比较大的话？比方说像三十多岁有不同。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000260",
        "start_ms": 1389010,
        "end_ms": 1394360,
        "speaker_id": "unknown",
        "text": "咱们主要招收的还是青年教官，因为他需要有非常我们学校的一个。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000261",
        "start_ms": 1394360,
        "end_ms": 1401985,
        "speaker_id": "speaker_0",
        "text": "那他青年教官会不会没有经验呢？相对于老兵来说，经验较少。主要招的是这种。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000262",
        "start_ms": 1399985,
        "end_ms": 1419590,
        "speaker_id": "speaker_3",
        "text": "当，就是当届的退伍兵啊。就比如说他是士官或者什么？呃，当届的退伍回来的一些士兵都符合要求又，就是岁数也没有那么大，就是也也能比较有经验一些。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000263",
        "start_ms": 1419590,
        "end_ms": 1439590,
        "speaker_id": "unknown",
        "text": "我现在需要这个招生办最终确定，这个最后招收、最终招中的人数。还要提前向他们查询他们的身高体重或者穿衣服的呃尺寸号码。我需要提前在他们开始前就向往这个……",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000264",
        "start_ms": 1439590,
        "end_ms": 1457950,
        "speaker_id": "unknown",
        "text": "服装生产厂家。制定，定的方案吗？这个到时候你和那个客户、或者一个厂长一起商量一下吧。对不对？好名单之后我们再上那个服装生产厂家。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000265",
        "start_ms": 1457950,
        "end_ms": 1474030,
        "speaker_id": "speaker_0",
        "text": "也可以看看招的是什么军官，海军啊、空军呀。一般这陆军系列的比较多，对。也可以整点新颖的：，一些海军空军。因为海兵和空军呢一合一个。这个的话是他们嗯。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000266",
        "start_ms": 1474030,
        "end_ms": 1479040,
        "speaker_id": "unknown",
        "text": "主要还是因为，因为他们这个财务可能就是。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000267",
        "start_ms": 1479040,
        "end_ms": 1482915,
        "speaker_id": "speaker_4",
        "text": "步兵的这个，步兵的训练方式可能更。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000268",
        "start_ms": 1480915,
        "end_ms": 1485915,
        "speaker_id": "speaker_3",
        "text": "适合于咱们这些学生。空间。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000269",
        "start_ms": 1483915,
        "end_ms": 1487910,
        "speaker_id": "speaker_0",
        "text": "学生。那你们对军训这方面有什么方案呢？",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000270",
        "start_ms": 1487910,
        "end_ms": 1496030,
        "speaker_id": "unknown",
        "text": "我建议，我建议咱们可以呃。为了提升他们的军训质量呢？",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000271",
        "start_ms": 1496030,
        "end_ms": 1513940,
        "speaker_id": "speaker_2",
        "text": "兴趣吧，呃坚坚持一天下来挺累的。可以晚上的时候嗯一两个小时吧适当让他们教官和学生一块儿对玩一下一个小游戏啊或者呃叫他们唱歌啊就可以。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000272",
        "start_ms": 1513940,
        "end_ms": 1519960,
        "speaker_id": "unknown",
        "text": "还有，可以让军训完以后给他们举行一个表演赛。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000273",
        "start_ms": 1519960,
        "end_ms": 1523240,
        "speaker_id": "speaker_0",
        "text": "对，分出来好了。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000274",
        "start_ms": 1521640,
        "end_ms": 1524500,
        "speaker_id": "speaker_3",
        "text": "哎，好的。军训会了？对。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000275",
        "start_ms": 1523590,
        "end_ms": 1534080,
        "speaker_id": "speaker_0",
        "text": "对，属于军训会演。让他们这样打打击他们的积极性，然后促进他们就是想好好的表演，在给咱们有一个奖项。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000276",
        "start_ms": 1534080,
        "end_ms": 1540480,
        "speaker_id": "unknown",
        "text": "这方面，就是你们稍微操心。还有就是。",
        "chapter_id": "chapter-8",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000277",
        "start_ms": 1540480,
        "end_ms": 1547780,
        "speaker_id": "speaker_0",
        "text": "学生，咱们学校比较热门的这专业是什么呀？叫什么。学生报得比较多的。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000278",
        "start_ms": 1547760,
        "end_ms": 1550550,
        "speaker_id": "speaker_4",
        "text": "它都是计算机了，因为现在周一是。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000279",
        "start_ms": 1550550,
        "end_ms": 1555260,
        "speaker_id": "unknown",
        "text": "比较好，机赛机这些的比较好。不过还有软件。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000280",
        "start_ms": 1555260,
        "end_ms": 1564650,
        "speaker_id": "speaker_0",
        "text": "那它会不会？如果计算机人报的太多的话，他以后反而不好找工作。就是特别没有市场了嘛！因为现在讲大形势。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000281",
        "start_ms": 1564650,
        "end_ms": 1567590,
        "speaker_id": "unknown",
        "text": "就是这样的，因为影视这个不单是吧。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000282",
        "start_ms": 1567590,
        "end_ms": 1572140,
        "speaker_id": "speaker_4",
        "text": "对，因为，在高科技方面，他们国家下力也是比较大的。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000283",
        "start_ms": 1572140,
        "end_ms": 1572760,
        "speaker_id": "unknown",
        "text": "对。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000284",
        "start_ms": 1572760,
        "end_ms": 1581345,
        "speaker_id": "speaker_0",
        "text": "说这方面，咱们这儿考证是要考。考证属于是毕业以后让他们自己考的还是学校安排呢？他们三。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000285",
        "start_ms": 1579345,
        "end_ms": 1583595,
        "speaker_id": "speaker_4",
        "text": "还是学校安排呢？咱们在学校，自己的话也是有要求。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000286",
        "start_ms": 1581595,
        "end_ms": 1584345,
        "speaker_id": "speaker_1",
        "text": "学校都会提供。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000287",
        "start_ms": 1582345,
        "end_ms": 1586300,
        "speaker_id": "speaker_2",
        "text": "机会，然后学生自愿。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000288",
        "start_ms": 1586300,
        "end_ms": 1588520,
        "speaker_id": "unknown",
        "text": "但是，咱们也会。就是。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000289",
        "start_ms": 1588520,
        "end_ms": 1594115,
        "speaker_id": "speaker_4",
        "text": "像他们毕业以后，咱们也会做一定的要求。像咱。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000290",
        "start_ms": 1592115,
        "end_ms": 1609030,
        "speaker_id": "speaker_2",
        "text": "像咱们学校的话，嗯后勤这边可以呃有安排很多那个计算机啊、计算机设备的教室。呃这方面是咱们学校的优势嘛？所以报咱们学校这个专业的就比较多。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000291",
        "start_ms": 1608630,
        "end_ms": 1612960,
        "speaker_id": "speaker_0",
        "text": "那这个计算机老师会不会人手配备一台笔记本？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000292",
        "start_ms": 1612850,
        "end_ms": 1620970,
        "speaker_id": "speaker_4",
        "text": "这个电脑的话，是大家需要免费要提供。因为咱们实验室里也有用。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000293",
        "start_ms": 1620780,
        "end_ms": 1623860,
        "speaker_id": "speaker_2",
        "text": "咱们都在实验室里面配备着。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000294",
        "start_ms": 1623860,
        "end_ms": 1632770,
        "speaker_id": "unknown",
        "text": "教师用的专用的呃，设备。对因为做项目需要的条件不是特别好。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000295",
        "start_ms": 1632770,
        "end_ms": 1639180,
        "speaker_id": "speaker_0",
        "text": "那上一季度，这边财务也报表了说。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000296",
        "start_ms": 1639180,
        "end_ms": 1641970,
        "speaker_id": "unknown",
        "text": "没有什么，开车。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000297",
        "start_ms": 1641970,
        "end_ms": 1650150,
        "speaker_id": "speaker_0",
        "text": "下一季度，咱们可以把这些省下的开销用来学生。那咱们学校用摄影校服吗？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000298",
        "start_ms": 1649280,
        "end_ms": 1653170,
        "speaker_id": "speaker_3",
        "text": "像普通话，大学去。但是比较少是吧？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000299",
        "start_ms": 1652540,
        "end_ms": 1655790,
        "speaker_id": "speaker_4",
        "text": "不需要，因为你像在对学生。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000300",
        "start_ms": 1655790,
        "end_ms": 1656690,
        "speaker_id": "unknown",
        "text": "我看的是。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000301",
        "start_ms": 1656690,
        "end_ms": 1660210,
        "speaker_id": "speaker_0",
        "text": "那会有戏服之类的吗？，戏服的话。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000302",
        "start_ms": 1660210,
        "end_ms": 1664160,
        "speaker_id": "unknown",
        "text": "只是会在特殊场合，就是运动会啊和三一四。但是",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000303",
        "start_ms": 1664160,
        "end_ms": 1669200,
        "speaker_id": "speaker_1",
        "text": "其实我觉得，衣服像学校。其实有准备就行到那天的时候。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000304",
        "start_ms": 1669200,
        "end_ms": 1671780,
        "speaker_id": "unknown",
        "text": "发下去就行，不用说在每个人。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000305",
        "start_ms": 1671780,
        "end_ms": 1674890,
        "speaker_id": "speaker_1",
        "text": "定一套，没有必要。不所有人都有厂。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000306",
        "start_ms": 1672900,
        "end_ms": 1681500,
        "speaker_id": "speaker_3",
        "text": "准备，准备一些就可以了。而且这个对这个人是长远的，一直都可以备用。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000307",
        "start_ms": 1675840,
        "end_ms": 1678890,
        "speaker_id": "speaker_2",
        "text": "对，一些费用。这个也是成。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000308",
        "start_ms": 1681500,
        "end_ms": 1682580,
        "speaker_id": "unknown",
        "text": "那咱们学校。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000309",
        "start_ms": 1682580,
        "end_ms": 1689080,
        "speaker_id": "speaker_0",
        "text": "如果举办运动会的话，是在本校举行呢？还是就比如说迎新生运动会。咱们本科操。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000310",
        "start_ms": 1689080,
        "end_ms": 1695070,
        "speaker_id": "unknown",
        "text": "是，因为其中反对党的呃嗯被动会反对。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000311",
        "start_ms": 1695070,
        "end_ms": 1697870,
        "speaker_id": "speaker_1",
        "text": "在本校办也比较好。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000312",
        "start_ms": 1697010,
        "end_ms": 1699840,
        "speaker_id": "speaker_3",
        "text": "毕竟安全。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000313",
        "start_ms": 1699200,
        "end_ms": 1702240,
        "speaker_id": "speaker_0",
        "text": "行了，这个安保不做。你是有什么？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000314",
        "start_ms": 1701740,
        "end_ms": 1731740,
        "speaker_id": "speaker_3",
        "text": "安排？安保就呢，一个是保证这个：因为运动会呃难免会出现一些学生中暑。嗯，这个也会及时的向这财务部门申报去购置一些这个清凉解暑物品；再一个就是，准备一些药品防止这些学生的就是运运动拉伤啊或者是碰撞呀之类的，就是产生这一系列不必要的受伤。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000315",
        "start_ms": 1731200,
        "end_ms": 1740860,
        "speaker_id": "speaker_0",
        "text": "那这方面让教务主任去给下边的导员说一声吧，让他们采购一些西瓜之类的。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000316",
        "start_ms": 1731740,
        "end_ms": 1733200,
        "speaker_id": "speaker_3",
        "text": "那这方面。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000317",
        "start_ms": 1740860,
        "end_ms": 1746320,
        "speaker_id": "unknown",
        "text": "这个不需要不清楚，爸爸妈妈。因为我们时常都会听习惯似的写。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000318",
        "start_ms": 1746320,
        "end_ms": 1750030,
        "speaker_id": "speaker_0",
        "text": "嗯，然后最好再找几个男同学去。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000319",
        "start_ms": 1749900,
        "end_ms": 1762740,
        "speaker_id": "speaker_4",
        "text": "现在，然后财务。现在呃不是，现在交付部有一个问题就是：咱们的软件需要更新了。软件也需要更新啊！对像一个软件的话，它现在最新的软件都是花。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000320",
        "start_ms": 1757025,
        "end_ms": 1760525,
        "speaker_id": "speaker_0",
        "text": "软件需要更新了。对，你像一个软件的话。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000321",
        "start_ms": 1762740,
        "end_ms": 1772120,
        "speaker_id": "unknown",
        "text": "上风险了，然后这就需要向财务进行报款。因为感觉一个实验室不大一个小的。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000322",
        "start_ms": 1772120,
        "end_ms": 1776840,
        "speaker_id": "speaker_0",
        "text": "可以，那你你定一个表格。然后价格不要定的很高。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000323",
        "start_ms": 1776440,
        "end_ms": 1779510,
        "speaker_id": "speaker_4",
        "text": "哦，因为价格的话，这不是咱们需要。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000324",
        "start_ms": 1779510,
        "end_ms": 1785280,
        "speaker_id": "unknown",
        "text": "是咱们，就是你可以直接向公司进行购买。想。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000325",
        "start_ms": 1785280,
        "end_ms": 1789905,
        "speaker_id": "speaker_0",
        "text": "那其他人还有什么意见吗？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000326",
        "start_ms": 1787905,
        "end_ms": 1791405,
        "speaker_id": "speaker_3",
        "text": "安保就那么用了。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000327",
        "start_ms": 1789405,
        "end_ms": 1794250,
        "speaker_id": "speaker_1",
        "text": "嗯，不我就那没有了。招生办这边儿没有就筹备一下新学期的。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000328",
        "start_ms": 1794250,
        "end_ms": 1796290,
        "speaker_id": "unknown",
        "text": "宣传海报，招生。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000329",
        "start_ms": 1796290,
        "end_ms": 1799220,
        "speaker_id": "speaker_0",
        "text": "行，那你做一个报表。到时候报给财务了。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000330",
        "start_ms": 1799220,
        "end_ms": 1801410,
        "speaker_id": "unknown",
        "text": "好。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000331",
        "start_ms": 1801410,
        "end_ms": 1806210,
        "speaker_id": "speaker_2",
        "text": "后勤这边儿工作，呃就没有了。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000332",
        "start_ms": 1806210,
        "end_ms": 1811090,
        "speaker_id": "unknown",
        "text": "行，叫主人也没法。没有下一个操作。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000333",
        "start_ms": 1811090,
        "end_ms": 1815820,
        "speaker_id": "speaker_5",
        "text": "行，那明天这场会议我先看到这儿。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000334",
        "start_ms": 1815820,
        "end_ms": 1835820,
        "speaker_id": "unknown",
        "text": "嗯，下去之后这个呃副院长这边把所有部门的控制和监督好安排好行吧？需要什么问题啊对。",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000335",
        "start_ms": 1835820,
        "end_ms": 1855820,
        "speaker_id": "unknown",
        "text": "",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      },
      {
        "segment_id": "seg-000336",
        "start_ms": 1855820,
        "end_ms": 1862276,
        "speaker_id": "unknown",
        "text": "不行，行不行？",
        "chapter_id": "chapter-9",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      }
    ]
  },
  "speakers": [
    {
      "speaker_id": "unknown",
      "display_name": "unknown",
      "segment_count": 116,
      "duration_ms": 607266,
      "user_renamed": false
    },
    {
      "speaker_id": "speaker_5",
      "display_name": "speaker_5",
      "segment_count": 4,
      "duration_ms": 22735,
      "user_renamed": false
    },
    {
      "speaker_id": "speaker_0",
      "display_name": "speaker_0",
      "segment_count": 81,
      "duration_ms": 455705,
      "user_renamed": false,
      "summary": "讨论了疫情期间学校财务、学生费用退返、设备维修、安保安排、食堂问题、宿舍管理、军训安排、招生计划以及校园活动等具体问题。"
    },
    {
      "speaker_id": "speaker_3",
      "display_name": "speaker_3",
      "segment_count": 30,
      "duration_ms": 243905,
      "user_renamed": false,
      "summary": "讨论了疫情期间安保措施、校园活动安排、学生管理、设备检查、消防演练、军训安排以及校园环境维护等问题。"
    },
    {
      "speaker_id": "speaker_1",
      "display_name": "speaker_1",
      "segment_count": 26,
      "duration_ms": 169015,
      "user_renamed": false,
      "summary": "讨论了招生宣传、财务预算、校园安全、消防演练、军训安排、学生管理、校园环境维护以及招生计划等方面的具体建议和方案。"
    },
    {
      "speaker_id": "speaker_2",
      "display_name": "speaker_2",
      "segment_count": 27,
      "duration_ms": 268325,
      "user_renamed": false,
      "summary": "提出食堂管理、宿舍设施、设备检查、消防安全、校园环境维护、军训安排以及招生宣传等方面的具体建议和方案。"
    },
    {
      "speaker_id": "speaker_4",
      "display_name": "speaker_4",
      "segment_count": 38,
      "duration_ms": 187140,
      "user_renamed": false,
      "summary": "提出考试方式、军训安排、学生管理、财务预算、校园安全、消防演练、招生宣传等方面的具体建议和方案。"
    },
    {
      "speaker_id": "speaker_6",
      "display_name": "speaker_6",
      "segment_count": 14,
      "duration_ms": 82205,
      "user_renamed": false,
      "summary": "提出住宿费退返、书费退返、设备维修、财务预算、教学质量提升等具体问题和建议。"
    }
  ],
  "minutes": {
    "overview": "会议围绕疫情后学校运营、教学安排及防疫措施展开讨论。上半年因疫情学生在家上网课，教师反馈网课效率不高，下半年需调整教学方式并制定考试安排。疫情期间学校开销减少，主要支出为教师薪资和设备维修，安保部门裁员部分员工居家休息。食堂因无人使用空闲，需定期消毒并调整运营模式。住宿费退一半、书费不退的政策已确定，财务部省下水电经费用于提升教学质量。宿舍设施需检查并完善，强调安全用电和消防措施。校园宣传通过社团活动和航拍进行，军训安排需明确教官来源及服装方案，计算机专业招生与教学资源配置也纳入讨论。",
    "outline": [
      {
        "node_id": "chapter-1",
        "level": 1,
        "title": "会议开场与议题讨论",
        "text": "会议由副院长主持，各部门负责人到场。上半年因疫情原因，学生主要在家上网课，教师反馈网课效率不高，下半年需调整教学方式。下半年将开学并招生，需制定考试安排，部分课程需返校后考试，如高数、专业课。住宿费已返还一半，需进一步处理退款问题。",
        "evidence_ids": [
          "evidence-seg-000009",
          "evidence-seg-000014",
          "evidence-seg-000023"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-2",
        "level": 1,
        "title": "疫情后学校运营与防疫措施讨论",
        "text": "疫情后学校运营与防疫措施讨论，疫情期间学校未开学，学生在家上网课，导致学校开销减少。主要支出为教师薪资和设备维修，安保部门裁员部分员工居家休息。疫情期间场地未开放，但夏季将有篮球比赛，需加强防疫措施如消毒、隔离和观众入场限制。开学后需进行学生面试和毕业证发放等流程。",
        "evidence_ids": [
          "evidence-seg-000041",
          "evidence-seg-000053",
          "evidence-seg-000072"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-3",
        "level": 1,
        "title": "食堂运营与防疫措施调整",
        "text": "疫情期间学校未开学，食堂因无人使用而空闲，需定期消毒以确保卫生安全。食堂窗口数量减少导致收入下降，承包商需根据实际情况调整运营模式。部分教职工可能需要在校内住宿，教职工宿舍费用与学生宿舍费用不同。",
        "evidence_ids": [
          "evidence-seg-000100",
          "evidence-seg-000104"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-4",
        "level": 1,
        "title": "退费政策与资源优化讨论",
        "text": "本块讨论了住宿费退一半、书费不退的退费政策，因半年未使用而退住宿费。财务部已撤出相关讨论，省下水电经费可用于提升教学质量，并考虑为教师提供额外支持。后勤部在节日期间会赠送部分物资。",
        "evidence_ids": [
          "evidence-seg-000126",
          "evidence-seg-000137",
          "evidence-seg-000148"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-5",
        "level": 1,
        "title": "宿舍设施与安全措施讨论",
        "text": "本块讨论宿舍设施是否完善，需检查设备损坏情况，并建议将部分资金用于招生宣传和招生咨询。同时强调学校硬件设施和教育质量在宣传中的重要性，提出宿舍用电安全问题，不建议使用大功率电器，并每栋楼需配备灭火器并进行消防演练。",
        "evidence_ids": [
          "evidence-seg-000153",
          "evidence-seg-000163",
          "evidence-seg-000184"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-6",
        "level": 1,
        "title": "校园活动与设施维护讨论",
        "text": "本块讨论校园宣传需通过社团活动和官网介绍学校，财务预算需由招生办制定具体计划。宿舍热水问题需解决，考虑二次加压或太阳能方案，水压不足问题需检修，高峰期用水问题需关注。",
        "evidence_ids": [
          "evidence-seg-000189",
          "evidence-seg-000202"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-7",
        "level": 1,
        "title": "军训安排与校园宣传讨论",
        "text": "本块讨论校园宣传需通过航拍和安保部门合作进行，考虑在楼顶安装设备以方便学生使用。军训是必须参加的，但可以考虑推迟或增加互动活动，促进关系融洽，并提升综合素质。教官来源需明确，可能从消防队等外部单位招聘。",
        "evidence_ids": [
          "evidence-seg-000220",
          "evidence-seg-000223",
          "evidence-seg-000237"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-8",
        "level": 1,
        "title": "军训教官来源与服装方案讨论",
        "text": "本块讨论从退伍兵中招募军训教官，考虑引入海军、空军等不同兵种，并需与服装生产厂家合作制定方案。建议增加互动活动如小游戏和表演赛以提升军训质量。",
        "evidence_ids": [
          "evidence-seg-000255",
          "evidence-seg-000263",
          "evidence-seg-000271"
        ],
        "review_status": "pending",
        "user_edited": false
      },
      {
        "node_id": "chapter-9",
        "level": 1,
        "title": "计算机专业招生与教学资源配置讨论",
        "text": "本块讨论计算机专业是热门专业，学生报考人数多，需关注就业前景。学校提供实验室和计算机设备支持，并为运动会准备校服和药品。计算机专业毕业生就业前景受关注，需考虑市场变化。",
        "evidence_ids": [
          "evidence-seg-000277",
          "evidence-seg-000290"
        ],
        "review_status": "pending",
        "user_edited": false
      }
    ]
  },
  "chapters": [
    {
      "chapter_id": "chapter-1",
      "index": 1,
      "title": "会议开场与议题讨论",
      "summary": "会议由副院长主持，各部门负责人到场。上半年因疫情原因，学生主要在家上网课，教师反馈网课效率不高，下半年需调整教学方式。下半年将开学并招生，需制定考试安排，部分课程需返校后考试，如高数、专业课。住宿费已返还一半，需进一步处理退款问题。",
      "start_ms": 36680,
      "end_ms": 236470,
      "evidence_ids": [
        "evidence-seg-000009",
        "evidence-seg-000014",
        "evidence-seg-000023"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-2",
      "index": 2,
      "title": "疫情后学校运营与防疫措施讨论",
      "summary": "疫情后学校运营与防疫措施讨论，疫情期间学校未开学，学生在家上网课，导致学校开销减少。主要支出为教师薪资和设备维修，安保部门裁员部分员工居家休息。疫情期间场地未开放，但夏季将有篮球比赛，需加强防疫措施如消毒、隔离和观众入场限制。开学后需进行学生面试和毕业证发放等流程。",
      "start_ms": 236470,
      "end_ms": 517830,
      "evidence_ids": [
        "evidence-seg-000041",
        "evidence-seg-000053",
        "evidence-seg-000072"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-3",
      "index": 3,
      "title": "食堂运营与防疫措施调整",
      "summary": "疫情期间学校未开学，食堂因无人使用而空闲，需定期消毒以确保卫生安全。食堂窗口数量减少导致收入下降，承包商需根据实际情况调整运营模式。部分教职工可能需要在校内住宿，教职工宿舍费用与学生宿舍费用不同。",
      "start_ms": 517830,
      "end_ms": 699790,
      "evidence_ids": [
        "evidence-seg-000100",
        "evidence-seg-000104"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-4",
      "index": 4,
      "title": "退费政策与资源优化讨论",
      "summary": "本块讨论了住宿费退一半、书费不退的退费政策，因半年未使用而退住宿费。财务部已撤出相关讨论，省下水电经费可用于提升教学质量，并考虑为教师提供额外支持。后勤部在节日期间会赠送部分物资。",
      "start_ms": 699790,
      "end_ms": 852270,
      "evidence_ids": [
        "evidence-seg-000126",
        "evidence-seg-000137",
        "evidence-seg-000148"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-5",
      "index": 5,
      "title": "宿舍设施与安全措施讨论",
      "summary": "本块讨论宿舍设施是否完善，需检查设备损坏情况，并建议将部分资金用于招生宣传和招生咨询。同时强调学校硬件设施和教育质量在宣传中的重要性，提出宿舍用电安全问题，不建议使用大功率电器，并每栋楼需配备灭火器并进行消防演练。",
      "start_ms": 858100,
      "end_ms": 1057945,
      "evidence_ids": [
        "evidence-seg-000153",
        "evidence-seg-000163",
        "evidence-seg-000184"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-6",
      "index": 6,
      "title": "校园活动与设施维护讨论",
      "summary": "本块讨论校园宣传需通过社团活动和官网介绍学校，财务预算需由招生办制定具体计划。宿舍热水问题需解决，考虑二次加压或太阳能方案，水压不足问题需检修，高峰期用水问题需关注。",
      "start_ms": 1055945,
      "end_ms": 1194970,
      "evidence_ids": [
        "evidence-seg-000189",
        "evidence-seg-000202"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-7",
      "index": 7,
      "title": "军训安排与校园宣传讨论",
      "summary": "本块讨论校园宣传需通过航拍和安保部门合作进行，考虑在楼顶安装设备以方便学生使用。军训是必须参加的，但可以考虑推迟或增加互动活动，促进关系融洽，并提升综合素质。教官来源需明确，可能从消防队等外部单位招聘。",
      "start_ms": 1194970,
      "end_ms": 1365795,
      "evidence_ids": [
        "evidence-seg-000220",
        "evidence-seg-000223",
        "evidence-seg-000237"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-8",
      "index": 8,
      "title": "军训教官来源与服装方案讨论",
      "summary": "本块讨论从退伍兵中招募军训教官，考虑引入海军、空军等不同兵种，并需与服装生产厂家合作制定方案。建议增加互动活动如小游戏和表演赛以提升军训质量。",
      "start_ms": 1363795,
      "end_ms": 1540480,
      "evidence_ids": [
        "evidence-seg-000255",
        "evidence-seg-000263",
        "evidence-seg-000271"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "chapter_id": "chapter-9",
      "index": 9,
      "title": "计算机专业招生与教学资源配置讨论",
      "summary": "本块讨论计算机专业是热门专业，学生报考人数多，需关注就业前景。学校提供实验室和计算机设备支持，并为运动会准备校服和药品。计算机专业毕业生就业前景受关注，需考虑市场变化。",
      "start_ms": 1540480,
      "end_ms": 1862276,
      "evidence_ids": [
        "evidence-seg-000277",
        "evidence-seg-000290"
      ],
      "review_status": "pending",
      "user_edited": false
    }
  ],
  "decisions": [
    {
      "decision_id": "decision-e1",
      "text": "下半年将不再采用网课，改为返校上课，并安排期末考试。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e2",
      "text": "疫情期间住宿费返还一半，学费暂不处理。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e3",
      "text": "疫情期间学校主要支出为教师薪资和设备维修。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e4",
      "text": "允许部分观众入场，但需做好消毒和防护措施。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e5",
      "text": "要求教职工每日到校值班，并做好消毒杀菌工作。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e6",
      "text": "学生需提前一周返校，并进行每日打卡。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e7",
      "text": "食堂因疫情期间学生不在校，需定期消毒。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e8",
      "text": "食堂因疫情期间学生不在校，窗口数量减少，导致收入减少。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e9",
      "text": "食堂承包商需定期检查卫生，确保消毒。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e10",
      "text": "学生因疫情退费，住宿费退一半。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e11",
      "text": "学校省下水电费用，用于提升教学质量。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e12",
      "text": "学校下半年应安排财务部门拨款用于招生宣传和咨询。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e13",
      "text": "宿舍设备需在下半年开学前进行检查，确保安全。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e14",
      "text": "学校宣传应突出硬件设施、教育质量、安全措施及食堂条件。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e15",
      "text": "将军训安排在开学后的学期末。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e16",
      "text": "在宿舍楼顶安装太阳能设备以解决供水不足问题。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e17",
      "text": "使用航拍仪对校园环境进行拍摄。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e18",
      "text": "主要招收青年教官，因为他们需要有学校要求的经验。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e19",
      "text": "可以考虑招收退伍兵作为教官，尤其是当届退伍兵。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "decision_id": "decision-e20",
      "text": "需要提前确定招生人数，并与服装生产厂家协商制定服装方案。",
      "evidence_ids": [],
      "review_status": "pending",
      "user_edited": false
    }
  ],
  "action_items": [
    {
      "action_id": "action-1",
      "text": "检查宿舍设备",
      "owner": null,
      "due_date": null,
      "evidence_ids": [
        "evidence-seg-000163"
      ],
      "review_status": "pending",
      "user_edited": false
    },
    {
      "action_id": "action-2",
      "text": "财务部资金分配",
      "owner": null,
      "due_date": null,
      "evidence_ids": [
        "evidence-seg-000170"
      ],
      "review_status": "pending",
      "user_edited": false
    }
  ],
  "enrichment": {
    "keywords": [
      "招生办",
      "院长",
      "服务员",
      "保卫科",
      "后勤部",
      "教务主任",
      "上半年总结会议",
      "网课",
      "考试安排",
      "住宿费退款",
      "设备维修",
      "安保部门",
      "疫情防控",
      "食堂管理",
      "招生宣传",
      "校园环境",
      "军训安排",
      "学生宿舍"
    ],
    "quotes": [
      {
        "quote": "嗯，行。咱们今天把各部门儿叫过来开个咱上半年的总结会议。呃，接下来由咱们这个副院长来主持一下这会。",
        "comment": "这句话点明了会议的核心目的，即对上半年的工作进行总结和规划，是整个会议的起点和核心议题。",
        "segment_id": "seg-000009",
        "speaker_id": "speaker_5"
      },
      {
        "quote": "提议说网课的效率不是很好，这个教育主任什么建议或者什么方案。呃，咱们由于上半年啊都是那个在家上的那个网课。",
        "comment": "这句话反映了疫情期间教学模式的转变以及教师对网课效果的担忧，是会议中讨论的重点问题之一。",
        "segment_id": "seg-000014",
        "speaker_id": "unknown"
      },
      {
        "quote": "咱们宿舍这方面的话，其实嗯其实是环境是比较好的。呃配备着配都是独立卫生间然后安装着空调啊这一段时间是完善了一下因为设备不是半年都宿舍空闲下来嘛？嗯这如果下半年要要如果下半年要开学的话我建议咱们这边儿是检查一下那些设。",
        "comment": "这句话体现了对校园基础设施的评价，是会议中关于硬件设施和学生生活条件的重要讨论内容。",
        "segment_id": "seg-000163",
        "speaker_id": "speaker_2"
      }
    ],
    "qa": [
      {
        "question": "网课的效率不是很好，教育主任有什么建议或者方案？",
        "answer": "考试是以网络方式进行的。"
      },
      {
        "question": "英语的四六级是怎么考的？",
        "answer": "手机可以开始使用。"
      },
      {
        "question": "疫情期间学生的费用怎么退？",
        "answer": "目前只有住宿费返还了一半。"
      },
      {
        "question": "疫情期间学校有没有开过学？",
        "answer": "疫情期间没有开学。"
      },
      {
        "question": "安保部门在疫情期间是如何安排的？裁员了还是怎么着啊！",
        "answer": "安保部门确实进行了裁员，裁掉了一部分人，但仍在职人员仍需每天到校值班，并做好消毒杀菌工作。"
      },
      {
        "question": "疫情期间学校开销主要有哪些？",
        "answer": "学校的开销主要就是老师们的薪资，还有设备的维修。"
      },
      {
        "question": "设备维修具体包括哪些内容？",
        "answer": "比如说，空调这个更新换代，还有体育馆内的一些设备更新。"
      },
      {
        "question": "疫情期间学校有哪些具体的支出？",
        "answer": "设备的更新，还有职工们、教职工们的福利。"
      },
      {
        "question": "疫情期间学校篮球场会有比赛吗？",
        "answer": "在疫情期间没有比赛，但夏季疫情趋于平稳后，篮球场会有大约二十场比赛。"
      },
      {
        "question": "疫情期间学校有没有外人租用场地的情况？",
        "answer": "疫情期间没有外人租用场地的情况。"
      },
      {
        "question": "学校食堂的支出情况如何？",
        "answer": "食堂的支出情况需要进一步说明。"
      },
      {
        "question": "暑期还要进行打卡吗？",
        "answer": "需要进行打卡，包括暑期期间。"
      },
      {
        "question": "这承包的这些客户他们是住在学校有专门的宿舍吗？还是他们住在学校外面每天都要进出学校。",
        "answer": "承包方既不住在学校内，也不住在学校外，每天需要进出学校。"
      },
      {
        "question": "学生在这一块有反馈吗？",
        "answer": "有反面啊！一开始的时候，他们最开始的时候是他们要求的。"
      },
      {
        "question": "这个经费是属于什么？",
        "answer": "这个后勤部一般都会送一些什么？"
      },
      {
        "question": "学校就餐是属于，充卡里边儿还是直接用微信？",
        "answer": "现金的话不太好吗？我觉得。"
      },
      {
        "question": "宿舍设备是否需要检查？",
        "answer": "如果下半年要开学的话，建议检查宿舍设备是否有损坏或腐坏的电路。"
      },
      {
        "question": "如何处理宿舍设备问题？",
        "answer": "需要直接到时候给财务部报一下。"
      },
      {
        "question": "下半年应该怎么做？",
        "answer": "下半年要迎来新的招生，需要从财务部抽一部分钱用于招生宣传和咨询。"
      },
      {
        "question": "宣传材料应包含哪些内容？",
        "answer": "宣传材料中应突出学校的硬件设施、教育质量、安全措施、绿化、食堂等学生反映较好的方面。"
      },
      {
        "question": "宿舍是否允许使用大功率电器？",
        "answer": "为了安全，不建议在宿舍使用大功率电器，以免发生火灾。"
      },
      {
        "question": "每栋楼是否有灭火器？",
        "answer": "每栋楼都会放置三个灭火器，地点在新的灭火器地点。"
      },
      {
        "question": "是否需要进行消防演练？",
        "answer": "安保这边要进行消防演练，并安排学生参与，同时教导主任需推广社团活动。"
      },
      {
        "question": "如何宣传学校？",
        "answer": "需要进行宣传，包括在官网介绍社团、学生活动、志愿者活动、科科协等，并让报考学生了解学校。"
      },
      {
        "question": "经济预算由谁负责？",
        "answer": "经济预算需要各部门共同负责。"
      },
      {
        "question": "招生办这边的具体计划多少钱？",
        "answer": "主要是招生办这边。他这边调我这块做出来的具体的计划。"
      },
      {
        "question": "宿舍水压的问题怎么解决？",
        "answer": "这个是宿舍肯定会出现的问题。这个不是咱们硬件设施的问题。"
      },
      {
        "question": "高峰期的时候会不会出现供水不足的问题？",
        "answer": "高峰期的时候会出现。因为这个问题是比较少的。"
      },
      {
        "question": "军训会不会取消？",
        "answer": "必须要参加。好。"
      },
      {
        "question": "军训有没有新颖的活动吸引学生？",
        "answer": "如果学生有反馈，肯定会跟那些教官提前都说好。就是也不要说是为了军训而军训，应该在训练的过程中。"
      },
      {
        "question": "军训的目的是什么？",
        "answer": "军训的目的就是为了锻炼意志，提升学生的综合素质。"
      },
      {
        "question": "教官是如何选拔的？",
        "answer": "教官可以是退伍兵，也可以是从学校、军校中招来的有经验的人。"
      },
      {
        "question": "如何确定军训教官？",
        "answer": "需要招生办最终确定教官人数，并提前查询他们的身高体重或服装尺寸。"
      },
      {
        "question": "军训期间如何提升学生积极性？",
        "answer": "可以通过晚上适当让学生和教官一起玩游戏、唱歌，以及军训后举行表演赛来提升积极性。"
      },
      {
        "question": "学校热门专业是什么？",
        "answer": "学校热门专业主要是计算机类，因为现在计算机相关专业比较受欢迎。"
      },
      {
        "question": "考证属于是毕业以后让他们自己考的还是学校安排呢？",
        "answer": "学校都会提供机会，然后学生自愿。"
      },
      {
        "question": "计算机老师会不会人手配备一台笔记本？",
        "answer": "这个电脑的话，是大家需要免费要提供。因为咱们实验室里也有用。"
      },
      {
        "question": "那咱们学校用摄影校服吗？",
        "answer": "像普通话，大学去。但是比较少是吧？"
      },
      {
        "question": "会有戏服之类的吗？",
        "answer": "只是会在特殊场合，就是运动会啊和三一四。但是其实我觉得，衣服像学校。其实有准备就行到那天的时候。"
      },
      {
        "question": "如果举办运动会的话，是在本校举行呢？还是就比如说迎新生运动会？",
        "answer": "是，因为其中反对党的呃嗯被动会反对。"
      },
      {
        "question": "需要向财务报款吗？",
        "answer": "需要向财务进行报款。"
      },
      {
        "question": "价格不要定得很高，可以定一个表格吗？",
        "answer": "可以，那你定一个表格。然后价格不要定的很高。"
      },
      {
        "question": "价格是不是需要我们来定？",
        "answer": "是咱们，就是你可以直接向公司进行购买。"
      },
      {
        "question": "其他人还有没有意见？",
        "answer": "那其他人还有什么意见吗？"
      },
      {
        "question": "副院长这边需要安排什么？",
        "answer": "副院长这边把所有部门的控制和监督好安排好行吧？需要什么问题啊对。"
      }
    ]
  },
  "evidence": [
    {
      "evidence_id": "evidence-seg-000009",
      "segment_id": "seg-000009",
      "start_ms": 51015,
      "end_ms": 61310,
      "speaker_id": "speaker_5",
      "quote": "嗯，行。咱们今天把各部门儿叫过来开个咱上半年的总结会议。呃，接下来由咱们这个副院长来主持一下这会。"
    },
    {
      "evidence_id": "evidence-seg-000014",
      "segment_id": "seg-000014",
      "start_ms": 76050,
      "end_ms": 90690,
      "speaker_id": "unknown",
      "quote": "提议说网课的效率不是很好，这个教育主任什么建议或者什么方案。呃，咱们由于上半年啊都是那个在家上的那个网课。"
    },
    {
      "evidence_id": "evidence-seg-000023",
      "segment_id": "seg-000023",
      "start_ms": 140250,
      "end_ms": 156775,
      "speaker_id": "speaker_0",
      "quote": "这个什么？这个问题先走。这个先说老师上课的问题，老师这方面：上课的问题、考试安排的是什么样的？是以期末考试还是下半年返校来考试呢？是。"
    },
    {
      "evidence_id": "evidence-seg-000041",
      "segment_id": "seg-000041",
      "start_ms": 236470,
      "end_ms": 239550,
      "speaker_id": "unknown",
      "quote": "嗯，还有就是因为咱们疫情期间嘛。"
    },
    {
      "evidence_id": "evidence-seg-000053",
      "segment_id": "seg-000053",
      "start_ms": 291825,
      "end_ms": 296075,
      "speaker_id": "speaker_0",
      "quote": "这个，裁员的人都在家歇着吗？嗯。"
    },
    {
      "evidence_id": "evidence-seg-000072",
      "segment_id": "seg-000072",
      "start_ms": 402030,
      "end_ms": 406350,
      "speaker_id": "speaker_3",
      "quote": "对，这叫“”。这个好东西啊！"
    },
    {
      "evidence_id": "evidence-seg-000100",
      "segment_id": "seg-000100",
      "start_ms": 545820,
      "end_ms": 566105,
      "speaker_id": "speaker_2",
      "quote": "嗯，因为这个疫情呃我们学校不是没有开学吗？呃，这个食堂这些教职工租的这些地方就空闲下来了。因为，嗯没有人在学校嘛。但是这个卫生啊需要隔一段儿时间去打扫一下，因为要去消毒。"
    },
    {
      "evidence_id": "evidence-seg-000104",
      "segment_id": "seg-000104",
      "start_ms": 598000,
      "end_ms": 614370,
      "speaker_id": "speaker_2",
      "quote": "都不在学校，呃食堂开设的比较那个窗口比较少。嗯对但是有有老师需要去就餐但但是开设的窗口比较少所以咱们学校呃上半年这个食堂的收入。"
    },
    {
      "evidence_id": "evidence-seg-000126",
      "segment_id": "seg-000126",
      "start_ms": 719120,
      "end_ms": 725740,
      "speaker_id": "speaker_6",
      "quote": "没有少，那个住宿费退一半。对，住宿费用一半是因为他一年住这这些年这一半年。"
    },
    {
      "evidence_id": "evidence-seg-000137",
      "segment_id": "seg-000137",
      "start_ms": 765140,
      "end_ms": 775920,
      "speaker_id": "speaker_6",
      "quote": "设备，所以水电省下来很多的经费。咱们可以在嗯用这些经费人加那个增加一些教学质量。"
    },
    {
      "evidence_id": "evidence-seg-000148",
      "segment_id": "seg-000148",
      "start_ms": 842610,
      "end_ms": 858100,
      "speaker_id": "speaker_2",
      "quote": "嗯，就是像过节的话就会送一些应应节的一些产品就比如月饼啊或者送一些粽子啊然后过年的话会送一些呃油啊这些。"
    },
    {
      "evidence_id": "evidence-seg-000153",
      "segment_id": "seg-000153",
      "start_ms": 864010,
      "end_ms": 866770,
      "speaker_id": "speaker_4",
      "quote": "你像平时的话，可能教师在。"
    },
    {
      "evidence_id": "evidence-seg-000163",
      "segment_id": "seg-000163",
      "start_ms": 909480,
      "end_ms": 939480,
      "speaker_id": "speaker_2",
      "quote": "咱们宿舍这方面的话，其实嗯其实是环境是比较好的。呃配备着配都是独立卫生间然后安装着空调啊这一段时间是完善了一下因为设备不是半年都宿舍空闲下来嘛？嗯这如果下半年要要如果下半年要开学的话我建议咱们这边儿是检查一下那些设。"
    },
    {
      "evidence_id": "evidence-seg-000184",
      "segment_id": "seg-000184",
      "start_ms": 1040195,
      "end_ms": 1046695,
      "speaker_id": "speaker_2",
      "quote": "每幢楼层都会放置三个嗯灭火器地点。走到新的一"
    },
    {
      "evidence_id": "evidence-seg-000189",
      "segment_id": "seg-000189",
      "start_ms": 1058945,
      "end_ms": 1070920,
      "speaker_id": "speaker_0",
      "quote": "这个也让教导主任到时候去推广一下咱们学校之类的社团活动啊！也可以拉学生的兴趣或者什么学生部门儿啊组织一下这方面额活动。"
    },
    {
      "evidence_id": "evidence-seg-000202",
      "segment_id": "seg-000202",
      "start_ms": 1126660,
      "end_ms": 1131820,
      "speaker_id": "speaker_0",
      "quote": "哦，主要是招生办这边。他这边调我这块做出来的具体的计划。"
    },
    {
      "evidence_id": "evidence-seg-000220",
      "segment_id": "seg-000220",
      "start_ms": 1194970,
      "end_ms": 1198900,
      "speaker_id": "unknown",
      "quote": "就是在楼顶上安装一个，为了让学生们使用就更加方便。"
    },
    {
      "evidence_id": "evidence-seg-000223",
      "segment_id": "seg-000223",
      "start_ms": 1214270,
      "end_ms": 1231980,
      "speaker_id": "speaker_3",
      "quote": "嗯，安保这边儿就是一个是会就定期的对这个校园内的一些设施检查。航拍这边的话，就是咱们有那个专门的无人机，呃，无人机去拍摄要有一个看地哦啊！"
    },
    {
      "evidence_id": "evidence-seg-000237",
      "segment_id": "seg-000237",
      "start_ms": 1281355,
      "end_ms": 1289660,
      "speaker_id": "speaker_4",
      "quote": "句型是吧？你像学生，像我反映就是，在军训的时候他们教我们给买西瓜。呃这个行为的话就会特别受。"
    },
    {
      "evidence_id": "evidence-seg-000255",
      "segment_id": "seg-000255",
      "start_ms": 1363795,
      "end_ms": 1369600,
      "speaker_id": "speaker_3",
      "quote": "嗯，也可以招一些这个当届的退伍兵。啊！"
    },
    {
      "evidence_id": "evidence-seg-000263",
      "segment_id": "seg-000263",
      "start_ms": 1419590,
      "end_ms": 1439590,
      "speaker_id": "unknown",
      "quote": "我现在需要这个招生办最终确定，这个最后招收、最终招中的人数。还要提前向他们查询他们的身高体重或者穿衣服的呃尺寸号码。我需要提前在他们开始前就向往这个……"
    },
    {
      "evidence_id": "evidence-seg-000271",
      "segment_id": "seg-000271",
      "start_ms": 1496030,
      "end_ms": 1513940,
      "speaker_id": "speaker_2",
      "quote": "兴趣吧，呃坚坚持一天下来挺累的。可以晚上的时候嗯一两个小时吧适当让他们教官和学生一块儿对玩一下一个小游戏啊或者呃叫他们唱歌啊就可以。"
    },
    {
      "evidence_id": "evidence-seg-000277",
      "segment_id": "seg-000277",
      "start_ms": 1540480,
      "end_ms": 1547780,
      "speaker_id": "speaker_0",
      "quote": "学生，咱们学校比较热门的这专业是什么呀？叫什么。学生报得比较多的。"
    },
    {
      "evidence_id": "evidence-seg-000290",
      "segment_id": "seg-000290",
      "start_ms": 1592115,
      "end_ms": 1609030,
      "speaker_id": "speaker_2",
      "quote": "像咱们学校的话，嗯后勤这边可以呃有安排很多那个计算机啊、计算机设备的教室。呃这方面是咱们学校的优势嘛？所以报咱们学校这个专业的就比较多。"
    },
    {
      "evidence_id": "evidence-seg-000265",
      "segment_id": "seg-000265",
      "start_ms": 1457950,
      "end_ms": 1474030,
      "speaker_id": "speaker_0",
      "quote": "也可以看看招的是什么军官，海军啊、空军呀。一般这陆军系列的比较多，对。也可以整点新颖的：，一些海军空军。因为海兵和空军呢一合一个。这个的话是他们嗯。"
    },
    {
      "evidence_id": "evidence-seg-000056",
      "segment_id": "seg-000056",
      "start_ms": 319240,
      "end_ms": 347860,
      "speaker_id": "speaker_3",
      "quote": "嗯，在这个疫情期间是没有的。呃，这个是马上临近夏季呢？夏季的话，嗯，这个疫情也逐渐趋于平稳。在咱们学校那个篮球场的话也会有大大小、大大小小大概二十场比赛吧。然后做一个比赛的时候在一个比赛的同时我们是除了参赛队员和教练，我们是不允许有观众入场因为。"
    },
    {
      "evidence_id": "evidence-seg-000314",
      "segment_id": "seg-000314",
      "start_ms": 1701740,
      "end_ms": 1731740,
      "speaker_id": "speaker_3",
      "quote": "安排？安保就呢，一个是保证这个：因为运动会呃难免会出现一些学生中暑。嗯，这个也会及时的向这财务部门申报去购置一些这个清凉解暑物品；再一个就是，准备一些药品防止这些学生的就是运运动拉伤啊或者是碰撞呀之类的，就是产生这一系列不必要的受伤。"
    },
    {
      "evidence_id": "evidence-seg-000172",
      "segment_id": "seg-000172",
      "start_ms": 980485,
      "end_ms": 1009220,
      "speaker_id": "speaker_1",
      "quote": "也可以说一下。想法就是先，嗯首先咱们那个宣传海报上一定要：咱们学校的首先是咱们的硬件、硬件设施。因为现在很多其实很多学校并不是说都配有空调。对。咱们学校既然有这个硬件的话就可以先说出来然后就咱们学校的教育，然后各种呃各种细节安全，然后绿化，然后食堂，然后……咱们呢？嗯，这些。首先，咱们学生反映。"
    },
    {
      "evidence_id": "evidence-seg-000170",
      "segment_id": "seg-000170",
      "start_ms": 958810,
      "end_ms": 977235,
      "speaker_id": "speaker_1",
      "quote": "然后因为明天现在也高考了嘛，呃九月份会有新的同学啊来我们的学校。然后我现在就觉得是我们应该去财务那里抽一部分钱，然后把大部分放在招生宣传和招生咨询上面。宣传一下我们学校。行这个。"
    },
    {
      "evidence_id": "evidence-seg-000103",
      "segment_id": "seg-000103",
      "start_ms": 568000,
      "end_ms": 598000,
      "speaker_id": "speaker_2",
      "quote": "消毒。去的话，有人去的话肯定是需要消毒的。就是对呃对是有学校学校里有时候呃要安排人去嗯检检查一下嘛啊所以就需要去咱们那个食堂里面哦食堂里面需要的人不太多但是但是一段时间就需要去打扫一下因为咱们疫情期间学生。"
    },
    {
      "evidence_id": "evidence-seg-000319",
      "segment_id": "seg-000319",
      "start_ms": 1749900,
      "end_ms": 1762740,
      "speaker_id": "speaker_4",
      "quote": "现在，然后财务。现在呃不是，现在交付部有一个问题就是：咱们的软件需要更新了。软件也需要更新啊！对像一个软件的话，它现在最新的软件都是花。"
    },
    {
      "evidence_id": "evidence-seg-000037",
      "segment_id": "seg-000037",
      "start_ms": 218160,
      "end_ms": 229825,
      "speaker_id": "speaker_6",
      "quote": "嗯，目前只有这个住宿费返还了一半。因为我们交的这一年度，它是从上个、上上的去年的那个上半年就开始交了，交的是年。"
    }
  ],
  "diagnostics": null
} as MeetingResultV1;
