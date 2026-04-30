# This is a ablation study for the effort made by ARVO
# 1. Without srcmap
# 2. Without component checkout
# 3. Without Url Fixing
# 4. Without base Env

todo = [42516204, 42534760, 42481233, 42501667, 42478455, 42535583, 42529008, 42475832, 42532259, 42514195, 42521041, 42516841, 42488377, 42532364, 408025086, 42473751, 42485353, 42516512, 42513918, 42470300, 376726596, 42541396, 42516070, 42496364, 42513013, 429298576, 42496125, 42476906, 42520830, 42512329, 42527937, 42522402, 42532906, 42491223, 42534486, 42479378, 42536471, 42489857, 42498298, 42484302, 42523472, 42480742, 42491082, 42506214, 42476249, 42499979, 42479371, 42537419, 42512497, 42496725, 42498732, 42504386, 42523372, 42540431, 42500410, 42517095, 42500100, 42488142, 42485942, 42489773, 42509405, 42517605, 42514528, 42472718, 42497412, 42528813, 42526578, 42501939, 42483053, 42520197, 42489833, 42480315, 42506130, 42470308, 42479388, 42477095, 42483586, 42513224, 42536975, 42533950, 42484285, 419468837, 42531322, 42481079, 42495323, 42488418, 42481124, 42538285, 42520719, 42490846, 42477222, 42504672, 42493862, 42527438, 42482971, 42525160, 42523358, 42526269, 42483511, 42526897]

from arvo import xExplore, verify, evalSet_ResetEvalFeature, evalSet_NOSRCMAP, evalSet_NOREBASE, evalSet_NOURLFIX, evalSet_NOCOMPONENT, INFO
# from arvo import *
import arvo._profile as profile  # or: from . import _profile as profile


# Without srcmap
def eval_without_srcmap():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    xExplore(todo,"eval_without_srcmap.log",verify)

# Without base Env
def eval_without_base_env():
    evalSet_ResetEvalFeature()
    evalSet_NOREBASE(True)
    xExplore(todo,"eval_without_base_env.log",verify)

# Without Url Fixing
def eval_without_url_fixing():
    evalSet_ResetEvalFeature()
    evalSet_NOURLFIX(True)
    xExplore(todo,"eval_without_url_fix.log",verify)

# Without component checkout
def eval_without_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_component_checkout.log",verify)


def eval_without_srcmap_and_base_env():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOREBASE(True)

    xExplore(todo,"eval_without_srcmap_and_base_env.log",verify)

def eval_without_srcmap_and_url_fixing():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOURLFIX(True)
    xExplore(todo,"eval_without_srcmap_and_url_fixing.log",verify)

def eval_without_srcmap_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_srcmap_and_component_checkout.log",verify)

def eval_without_base_env_and_url_fixing():
    evalSet_ResetEvalFeature()
    evalSet_NOREBASE(True)
    evalSet_NOURLFIX(True)
    xExplore(todo,"eval_without_base_env_and_url_fixing.log",verify)

def eval_without_base_env_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOREBASE(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_base_env_and_component_checkout.log",verify)

def eval_without_url_fixing_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOURLFIX(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_url_fixing_and_component_checkout.log",verify)

def eval_without_srcmap_base_env_and_url_fixing():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOREBASE(True)
    evalSet_NOURLFIX(True)
    xExplore(todo,"eval_without_srcmap_base_env_and_url_fixing.log",verify)

def eval_without_srcmap_base_env_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOREBASE(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_srcmap_base_env_and_component_checkout.log",verify)

def eval_without_srcmap_url_fixing_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOURLFIX(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_srcmap_url_fixing_and_component_checkout.log",verify)

def eval_without_base_env_url_fixing_and_component_checkout():
    evalSet_ResetEvalFeature()
    evalSet_NOREBASE(True)
    evalSet_NOURLFIX(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_base_env_url_fixing_and_component_checkout.log",verify)

def eval_without_all_features():
    evalSet_ResetEvalFeature()
    evalSet_NOSRCMAP(True)
    evalSet_NOREBASE(True)
    evalSet_NOURLFIX(True)
    evalSet_NOCOMPONENT(True)
    xExplore(todo,"eval_without_all_features.log",verify)


if __name__ == "__main__":
    # Signle

    eval_without_base_env()
    INFO(f"[DONE] eval_without_base_env")
    eval_without_url_fixing()
    INFO(f"[DONE] url_fixing")
    eval_without_component_checkout()
    INFO(f"[DONE] component_checkout")
    eval_without_srcmap()
    INFO(f"[DONE] srcmap")

    # # Combo-2
    eval_without_srcmap_and_base_env()
    INFO(f"[DONE] srcmap_and_base_env")

    eval_without_srcmap_and_url_fixing()
    INFO(f"[DONE] srcmap_and_url_fixing")

    eval_without_srcmap_and_component_checkout()
    INFO(f"[DONE] srcmap_and_component_checkout")

    eval_without_base_env_and_url_fixing()
    INFO(f"[DONE] base_env_and_url_fixing")

    eval_without_base_env_and_component_checkout()
    INFO(f"[DONE] base_env_and_component_checkout")

    eval_without_url_fixing_and_component_checkout()
    INFO(f"[DONE] url_fixing_and_component_checkout")
    
    # # # Combo-3
    eval_without_srcmap_base_env_and_url_fixing()
    eval_without_srcmap_base_env_and_component_checkout()
    eval_without_srcmap_url_fixing_and_component_checkout()
    eval_without_base_env_url_fixing_and_component_checkout()

    # Disable all
    eval_without_all_features()

