import unittest
from unittest.mock import patch

from explorer.ai import LlamaCppModel, parse_output
from explorer.summary import one_sentence, extractive_sentence, source_sentences, normalize_source


class SourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.source = ('The cloud migration was rejected. '
                       'The team approved a local-only pilot for 20 users. '
                       'A production rollout has not been approved.')
        self.evidence = [dict(section='Decision', anchor='p. 12', text=self.source)]
        self.candidates = [dict(section='Decision', anchor='p. 12', text=sentence, evidence=self.source)
                           for sentence in source_sentences(self.source)]

    def test_model_selects_source_id_and_cannot_supply_displayed_wording(self):
        accepted, rejected = parse_output(' 2\n', self.candidates)
        self.assertEqual(rejected, 0)
        self.assertEqual(accepted[0]['text'], 'The team approved a local-only pilot for 20 users.')
        self.assertEqual(accepted[0]['anchor'], 'p. 12')
        self.assertEqual(accepted[0]['origin'], 'ai_selected')
        self.assertEqual(accepted[0]['verification'], 'source_sentence')

    def test_generated_claims_are_rejected_even_with_matching_vocabulary(self):
        claims = [
            'The cloud migration was approved.',
            'A production rollout has been approved.',
            'The team approved a local-only pilot for 200 users.',
            'The team did not approve a local-only pilot for 20 users.',
            '2026년 10월 26일 검증을 완료했습니다.',
            '1\nThe cloud migration was approved.',
            '1 | The cloud migration was approved.',
            '<think>Use claim 1.</think>1',
            self.candidates[0]['text'],
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertEqual(parse_output(claim, self.candidates), ([], 1))

    def test_zero_unknown_ids_and_multiple_choices_are_rejected(self):
        for output in ('0', '4', '-1', '1.0', '1 2', '01', '[1]', 'ID: 1', '1;2', '999999999999'):
            with self.subTest(output=output):
                self.assertEqual(parse_output(output, self.candidates), ([], 1))

    def test_well_formed_id_cannot_bypass_source_provenance_check(self):
        for altered in ('The cloud migration was approved.',
                        'The team approved a local-only pilot for 200 users.',
                        'A production rollout has been approved.'):
            item = dict(self.candidates[0], text=altered)
            self.assertEqual(parse_output('1', [item]), ([], 1))

    def test_date_and_event_from_different_sentences_cannot_be_joined(self):
        source = '2026년 10월 26일 제품 회의를 진행했습니다. 2026년 11월 2일까지 검증할 예정입니다.'
        forged = dict(section='Plan', anchor='줄 5', evidence=source,
                      text='2026년 10월 26일 검증을 완료했습니다.')
        self.assertEqual(parse_output('1', [forged]), ([], 1))

    def test_negation_qualifiers_and_numbers_are_kept_together(self):
        source = 'The pilot is approved only for testing, not for production.'
        candidates = LlamaCppModel.candidate_sentences([dict(section='Decision', anchor='p. 3', text=source)])
        selected, _ = parse_output('1', candidates)
        self.assertEqual(selected[0]['text'], source)
        self.assertIn('not for production', selected[0]['text'])

    def test_layout_whitespace_is_the_only_normalization(self):
        source = 'Revenue\nincreased by 18% in 2026. The review is scheduled, not completed.'
        candidates = LlamaCppModel.candidate_sentences([dict(section='Results', anchor='p. 4', text=source)])
        for candidate in candidates:
            self.assertIn(candidate['text'], normalize_source(source))
            self.assertIn(candidate['text'], source_sentences(source))
        self.assertTrue(any('18%' in item['text'] for item in candidates))

    def test_source_prefix_and_punctuation_are_not_rewritten(self):
        source = 'Summary: only manually approved files may be shared; automatic upload is disabled.'
        self.assertEqual(list(source_sentences(source)), [source])
        self.assertEqual(extractive_sentence([dict(section='Policy', anchor='p. 1', text=source)])['text'], source)

    def test_oversized_sentence_is_not_cropped_into_a_new_claim(self):
        source = 'This is a statement ' + 'with important qualifications ' * 12 + 'that must not be discarded.'
        self.assertEqual(list(source_sentences(source)), [])
        self.assertEqual(LlamaCppModel.candidate_sentences([dict(section='Notes', anchor='p. 1', text=source)]), [])

    def test_short_standalone_slide_bullet_can_be_used_without_added_words(self):
        source = 'Automatic document upload disabled'
        self.assertEqual(list(source_sentences(source)), [source])

    def test_page_headings_are_not_joined_to_a_different_paragraph(self):
        source = '03 / CONCLUSION\n\nThe parser processes\npages with a 256 MB limit.'
        self.assertEqual(list(source_sentences(source)), ['The parser processes pages with a 256 MB limit.'])

    def test_main_decision_is_retained_in_candidate_pool(self):
        evidence = [
            dict(section='회의 개요', anchor='줄 1', text='2026년 10월 26일 제품 회의를 진행했습니다.'),
            dict(section='사용자 요구', anchor='줄 4', text='파일 이름을 모르더라도 필요한 문서를 찾을 수 있어야 합니다.'),
            dict(section='주요 결정', anchor='줄 7', text='파일 탐색과 검색 및 문서 미리보기를 첫 배포에서 우선 제공합니다.'),
            dict(section='성능 기준', anchor='줄 10', text='RAM 4GB 이하에서도 파일 탐색 기능을 사용할 수 있어야 합니다.'),
            dict(section='다음 단계', anchor='줄 13', text='2026년 11월 2일까지 성능 검증을 진행할 예정입니다.')]
        candidates = LlamaCppModel.candidate_sentences(evidence)
        self.assertEqual(candidates[0]['section'], '주요 결정')
        self.assertTrue(all(item['text'] in source_sentences(item['evidence']) for item in candidates))

    def test_prompt_requests_an_id_and_keeps_source_unchanged(self):
        messages = LlamaCppModel.messages(self.candidates, 'Pilot decision')
        self.assertEqual([item['role'] for item in messages], ['system', 'user'])
        for item in self.candidates:
            self.assertIn(item['text'], messages[1]['content'])
        self.assertIn('integer ID', messages[1]['content'])
        self.assertNotIn('<|im_start|>', messages[1]['content'])

    def test_malformed_backend_response_falls_back_to_an_original_sentence(self):
        model = LlamaCppModel(dict(model_id='test', model_version='test'), '.')
        def call(endpoint, data=None, timeout=45):
            if endpoint == '/tokenize':
                return {'tokens': [1]}
            return {'content': 'The production rollout has been approved.', 'tokens_predicted': 8}
        with patch.object(model, 'prompt', return_value='test'), patch.object(model, 'call', side_effect=call):
            result = model.summarize(self.evidence)
        self.assertEqual(result['mode'], 'extractive_fallback')
        self.assertEqual(result['verification'], 'source_sentence')
        self.assertIn(result['summary_text'], source_sentences(self.source))
        self.assertNotEqual(result['summary_text'], 'The production rollout has been approved.')

    def test_one_sentence_result_contract_is_retained(self):
        for output in ('First result. Second result.', '[1] First result.\n[2] Second result.', 'unfinished'):
            self.assertIsNone(one_sentence(output))
        selected = extractive_sentence(self.evidence)
        self.assertIn(selected['text'], source_sentences(self.source))
        self.assertNotIn('\n', selected['text'])


if __name__ == '__main__':
    unittest.main()
