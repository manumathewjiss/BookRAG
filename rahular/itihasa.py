# coding=utf-8
# Copyright 2020 The TensorFlow Datasets Authors and the HuggingFace Datasets Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Itihasa Corpus."""


import collections

import datasets


_DESCRIPTION = """\
A Sanskrit-English machine translation dataset.
"""

_CITATION = """\
@inproceedings{aralikatte-etal-2021-itihasa,
    title = "Itihasa: A large-scale corpus for {S}anskrit to {E}nglish translation",
    author = "Aralikatte, Rahul  and
      de Lhoneux, Miryam  and
      Kunchukuttan, Anoop  and
      S{\o}gaard, Anders",
    booktitle = "Proceedings of the 8th Workshop on Asian Translation (WAT2021)",
    month = aug,
    year = "2021",
    address = "Online",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2021.wat-1.22",
    pages = "191--197",
    abstract = "This work introduces Itihasa, a large-scale translation dataset containing 93,000 pairs of Sanskrit shlokas and their English translations. The shlokas are extracted from two Indian epics viz., The Ramayana and The Mahabharata. We first describe the motivation behind the curation of such a dataset and follow up with empirical analysis to bring out its nuances. We then benchmark the performance of standard translation models on this corpus and show that even state-of-the-art transformer architectures perform poorly, emphasizing the complexity of the dataset.",
}
"""

_DATA_URL = "https://github.com/rahular/itihasa/archive/refs/heads/main.zip"

# Tuple that describes a single pair of files with matching translations.
# language_to_file is the map from language (2 letter string: example 'en')
# to the file path in the extracted directory.
TranslateData = collections.namedtuple("TranslateData", ["url", "language_to_file"])


class ItihasaConfig(datasets.BuilderConfig):
    """BuilderConfig for Itihasa."""

    def __init__(self, **kwargs):
        """BuilderConfig for Itihasa."""
        super(ItihasaConfig, self).__init__(
            name="Itihasa",
            description=_DESCRIPTION,
            version=datasets.Version("1.0.0", ""),
            **kwargs,
        )


class Itihasa(datasets.GeneratorBasedBuilder):
    """Itihasa machine translation dataset."""

    BUILDER_CONFIGS = [
        ItihasaConfig()
    ]

    def _info(self):
        return datasets.DatasetInfo(
            description=_DESCRIPTION,
            features=datasets.Features(
                {"translation": datasets.features.Translation(languages=("sn", "en"))}
            ),
            supervised_keys=("sn", "en"),
            homepage="http://www.rahular.com/itihasa/",
            citation=_CITATION,
        )

    def _split_generators(self, dl_manager):
        dl_dir = dl_manager.download_and_extract(_DATA_URL)

        source, target = "sn", "en"
        path_tmpl = "{dl_dir}/itihasa-main/data/{split}.{lang}"

        files = {}
        for split in ("train", "dev", "test"):
            files[split] = {
                "source_file": path_tmpl.format(dl_dir=dl_dir, split=split, lang=source),
                "target_file": path_tmpl.format(dl_dir=dl_dir, split=split, lang=target),
            }

        return [
            datasets.SplitGenerator(name=datasets.Split.TRAIN, gen_kwargs=files["train"]),
            datasets.SplitGenerator(name=datasets.Split.VALIDATION, gen_kwargs=files["dev"]),
            datasets.SplitGenerator(name=datasets.Split.TEST, gen_kwargs=files["test"]),
        ]

    def _generate_examples(self, source_file, target_file):
        """This function returns the examples in the raw (text) form."""
        with open(source_file, encoding="utf-8") as f:
            source_sentences = f.read().split("\n")
        with open(target_file, encoding="utf-8") as f:
            target_sentences = f.read().split("\n")

        assert len(target_sentences) == len(source_sentences), "Sizes do not match: %d vs %d for %s vs %s." % (
            len(source_sentences),
            len(target_sentences),
            source_file,
            target_file,
        )

        source, target = "sn", "en"
        for idx, (l1, l2) in enumerate(zip(source_sentences, target_sentences)):
            result = {"translation": {source: l1, target: l2}}
            # Make sure that both translations are non-empty.
            if all(result.values()):
                yield idx, result