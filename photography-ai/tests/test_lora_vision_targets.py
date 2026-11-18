"""lora.vision_lora_names: which vision-tower Linear layers get adapters."""

import mlx.nn as nn
import pytest

from photo_ai.training.lora import LoraConfig, vision_lora_names


class _Model:
    def __init__(self):
        lin = nn.Linear(4, 4)
        self._mods = []
        for b in range(4):
            for p in ("attn.qkv", "attn.proj", "mlp.linear_fc1", "mlp.linear_fc2"):
                self._mods.append((f"vision_tower.blocks.{b}.{p}", lin))
            self._mods.append((f"vision_tower.blocks.{b}.norm1", nn.LayerNorm(4)))
        for base in ("vision_tower.merger", "vision_tower.deepstack_merger_list.0"):
            self._mods += [(f"{base}.linear_fc1", lin), (f"{base}.linear_fc2", lin)]
        self._mods.append(("language_model.model.layers.0.self_attn.q_proj", lin))

    def named_modules(self):
        return self._mods


def test_default_config_leaves_vision_tower_untouched():
    assert LoraConfig().vision_targets == [] and vision_lora_names(_Model(), []) == []


def test_first_block_skips_lower_blocks_but_keeps_mergers():
    names = vision_lora_names(_Model(), ["qkv", "proj", "linear_fc1", "linear_fc2"], first_block=2)
    assert {n.split(".")[2] for n in names if ".blocks." in n} == {"2", "3"}
    assert "vision_tower.merger.linear_fc1" in names and "vision_tower.deepstack_merger_list.0.linear_fc2" in names
    assert not any(n.startswith("language_model") or n.endswith("norm1") for n in names)


def test_unknown_suffix_is_an_error():
    with pytest.raises(ValueError):
        vision_lora_names(_Model(), ["nope"])
