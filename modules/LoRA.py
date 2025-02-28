from pathlib import Path

import torch
from peft import PeftModel

import modules.shared as shared
from modules.logging_colors import logger
from modules.models import reload_model


def add_lora_to_model(lora_names):
    if 'GPTQForCausalLM' in shared.model.__class__.__name__:
        add_lora_autogptq(lora_names)
    elif shared.model.__class__.__name__ == 'ExllamaModel':
        add_lora_exllama(lora_names)
    else:
        add_lora_transformers(lora_names)


def add_lora_exllama(lora_names):

    try:
        from exllama.lora import ExLlamaLora
    except:
        try:
            from repositories.exllama.lora import ExLlamaLora
        except:
            logger.error("Could not find the file repositories/exllama/lora.py. Make sure that exllama is cloned inside repositories/ and is up to date.")
            return

    if len(lora_names) == 0:
        shared.model.generator.lora = None
        shared.lora_names = []
        return
    else:
        if len(lora_names) > 1:
            logger.warning('ExLlama can only work with 1 LoRA at the moment. Only the first one in the list will be loaded.')

        lora_path = Path(f"{shared.args.lora_dir}/{lora_names[0]}")
        lora_config_path = lora_path / "adapter_config.json"
        lora_adapter_path = lora_path / "adapter_model.bin"

        logger.info("Applying the following LoRAs to {}: {}".format(shared.model_name, ', '.join([lora_names[0]])))
        lora = ExLlamaLora(shared.model.model, str(lora_config_path), str(lora_adapter_path))
        shared.model.generator.lora = lora
        shared.lora_names = [lora_names[0]]
        return


# Adapted from https://github.com/Ph0rk0z/text-generation-webui-testing
def add_lora_autogptq(lora_names):

    try:
        from auto_gptq import get_gptq_peft_model
        from auto_gptq.utils.peft_utils import GPTQLoraConfig
    except:
        logger.error("This version of AutoGPTQ does not support LoRA. You need to install from source or wait for a new release.")
        return

    if len(lora_names) == 0:
        if len(shared.lora_names) > 0:
            reload_model()

        shared.lora_names = []
        return
    else:
        if len(lora_names) > 1:
            logger.warning('AutoGPTQ can only work with 1 LoRA at the moment. Only the first one in the list will be loaded.')

        peft_config = GPTQLoraConfig(
            inference_mode=True,
        )

        lora_path = Path(f"{shared.args.lora_dir}/{lora_names[0]}")
        logger.info("Applying the following LoRAs to {}: {}".format(shared.model_name, ', '.join([lora_names[0]])))
        shared.model = get_gptq_peft_model(shared.model, peft_config, lora_path)
        shared.lora_names = [lora_names[0]]
        return


def add_lora_transformers(lora_names):
    prior_set = set(shared.lora_names)
    added_set = set(lora_names) - prior_set
    removed_set = prior_set - set(lora_names)

    # If no LoRA needs to be added or removed, exit
    if len(added_set) == 0 and len(removed_set) == 0:
        return

    # Add a LoRA when another LoRA is already present
    if len(removed_set) == 0 and len(prior_set) > 0:
        logger.info(f"Adding the LoRA(s) named {added_set} to the model...")
        for lora in added_set:
            shared.model.load_adapter(Path(f"{shared.args.lora_dir}/{lora}"), lora)

        return

    # If any LoRA needs to be removed, start over
    if len(removed_set) > 0:
        shared.model.disable_adapter()
        shared.model = shared.model.base_model.model

    if len(lora_names) > 0:
        params = {}
        if not shared.args.cpu:
            params['dtype'] = shared.model.dtype
            if hasattr(shared.model, "hf_device_map"):
                params['device_map'] = {"base_model.model." + k: v for k, v in shared.model.hf_device_map.items()}
            elif shared.args.load_in_8bit:
                params['device_map'] = {'': 0}

        logger.info("Applying the following LoRAs to {}: {}".format(shared.model_name, ', '.join(lora_names)))
        shared.model = PeftModel.from_pretrained(shared.model, Path(f"{shared.args.lora_dir}/{lora_names[0]}"), adapter_name=lora_names[0], **params)
        for lora in lora_names[1:]:
            shared.model.load_adapter(Path(f"{shared.args.lora_dir}/{lora}"), lora)

        shared.lora_names = lora_names

        if not shared.args.load_in_8bit and not shared.args.cpu:
            shared.model.half()
            if not hasattr(shared.model, "hf_device_map"):
                if torch.has_mps:
                    device = torch.device('mps')
                    shared.model = shared.model.to(device)
                else:
                    shared.model = shared.model.cuda()
