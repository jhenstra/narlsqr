
import rustworkx as rx
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.policies import MaskableMultiInputActorCriticPolicy
from stable_baselines3.common.vec_env import SubprocVecEnv

from routing.circuit_gen import RandomCircuitGenerator
from routing.env import QcpRoutingEnv, NoiseConfig


def main():
    from rich import print
    from rustworkx.visualization import mpl_draw
    import matplotlib.pyplot as plt
    from qiskit.converters import dag_to_circuit
    from qiskit.transpiler import CouplingMap
    from qiskit import transpile

    # Parameters
    learn = True
    show_topology = False

    n_envs = 6
    n_iters_per_env = 200
    n_steps = 1024
    depth = 8
    noise_config = NoiseConfig(1e-2, 3e-3)

    routing_method = 'sabre'

    g = rx.PyGraph()
    g.add_nodes_from([0, 1, 2, 3, 4])
    g.add_edges_from_no_data([(0, 1), (1, 2), (1, 3), (3, 4)])

    if show_topology:
        rx.visualization.mpl_draw(g, with_labels=True)
        plt.show()

    def env_fn() -> QcpRoutingEnv:
        return QcpRoutingEnv(g, RandomCircuitGenerator(g.num_nodes(), 16), depth, noise_config=noise_config)

    vec_env = SubprocVecEnv([env_fn] * n_envs)

    try:
        model = MaskablePPO.load('m_qcp_routing.model', vec_env, tensorboard_log='routing_logs')
    except FileNotFoundError:
        policy_kwargs = {
            'net_arch': [64, 64, 96],
        }

        model = MaskablePPO(MaskableMultiInputActorCriticPolicy, vec_env, policy_kwargs=policy_kwargs, n_steps=n_steps,
                            tensorboard_log='routing_logs', learning_rate=5e-5)

    if learn:
        model.learn(n_envs * n_iters_per_env * n_steps, progress_bar=True)
        model.save('m_qcp_routing.model')

    env = env_fn()
    obs, _ = env.reset()

    initial_layout = env.qubit_to_node.copy().tolist()
    print(f'Initial depth: {env.circuit.depth()}')

    terminated = False
    total_reward = 0.0

    while not terminated:
        action, _ = model.predict(obs, action_masks=env.action_masks(), deterministic=False)
        action = int(action)

        obs, reward, terminated, *_ = env.step(action)
        total_reward += reward

    print(f'Total reward: {total_reward:.2f}\n')
    routed_circuit = dag_to_circuit(env.routed_dag)

    print('[b blue]RL Routing[/b blue]')
    print(f'Depth: {routed_circuit.depth()} | {routed_circuit.depth() / env.circuit.depth():.3f}')
    print(f'Swaps: {routed_circuit.count_ops()["swap"]}')

    routed_circuit = routed_circuit.decompose()
    print(f'CNOTs after decomposition: {routed_circuit.count_ops()["cx"]}')
    print(f'Depth after decomposition: {routed_circuit.depth()}\n')

    coupling_map = CouplingMap(g.to_directed().edge_list())
    t_qc = transpile(env.circuit, coupling_map=coupling_map, initial_layout=initial_layout,
                     routing_method=routing_method, basis_gates=['u', 'swap', 'cx'], optimization_level=0)

    print(f'[b blue]Qiskit Compiler ({routing_method} routing)[/b blue]')
    print(f'Depth: {t_qc.depth()} | {t_qc.depth() / env.circuit.depth():.3f}')
    print(f'Swaps: {t_qc.count_ops()["swap"]}')

    t_qc = t_qc.decompose()
    print(f'CNOTs after decomposition: {t_qc.count_ops()["cx"]}')
    print(f'Depth after decomposition: {t_qc.depth()}')


if __name__ == '__main__':
    main()
