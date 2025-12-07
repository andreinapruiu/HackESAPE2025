import torch

checkpoint = torch.load('d:/SAP_HackITall/HackESAPE2025/solver/models/dqn_agent_best.pth', weights_only=False)
print("Checkpoint keys:", checkpoint.keys())
print("\nCheckpoint structure:")
for key in checkpoint.keys():
    print(f"  {key}: {type(checkpoint[key])}")
