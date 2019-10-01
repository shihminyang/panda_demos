#!/usr/bin/env python
import sys
import math
import torch
import argparse
import importlib
import rospy
# rospy.init_node('main_learning_loop', anonymous=True)

import plotter_from_generated as plotter_module
from torch.distributions.multivariate_normal import MultivariateNormal

from datetime import datetime
import ast

import rospkg
rospack = rospkg.RosPack()
package_path = rospack.get_path("trajectory_generator")

parser = argparse.ArgumentParser(description='PyTorch REINFORCE example')
parser.add_argument('--gamma', type=float, default=0.99, metavar='G', help='discount factor (default: 0.99)')
parser.add_argument('--seed', type=int, default=543, metavar='N', help='random seed (default: 543)')
parser.add_argument('--no-cuda', action='store_true', default=False, help='enables CUDA training')

parser.add_argument('--pre-train-log-interval', type=int, default=10, metavar='N', help='interval between training status logs (default: 100)')
parser.add_argument('--pre-train-epochs', type=int, default=100, help='number of epochs for training (default: 1000)')
parser.add_argument('--pre-train-batch-size', type=int, default=100, metavar='N', help='input batch size for training (default: 1000)')
parser.add_argument('--log-interval', type=int, default=1, metavar='N', help='interval between training status logs (default: 1)')
parser.add_argument('--epochs', type=int, default=12, help='number of epochs for training (default: 10)')
parser.add_argument('--batch-size', type=int, default=5, metavar='N', help='input batch size for training (default: 12)')
parser.add_argument('--action-repetition', type=int, default=3 , help='number of times to  repeat the same action')
parser.add_argument('--safe-throws', type=int, default=180 , help='number of safe throws to execute before stopping the learning loop')

parser.add_argument('--state-dim', type=int, default=4, help='policy input dimension (default: 4)')
parser.add_argument('--action-dim', type=int, default=5, help='policy output dimension (default: 5)')
parser.add_argument('--learning-rate', type=float, default=0.01, help='learning rate of the optimizer')

parser.add_argument('--models-dir', default="nn_models", help='directory from where to load the network shape of the action decoder')
parser.add_argument('--decoder-model-file', default="model_trajectory_vae", help='file from where to load the network shape of the action decoder')
parser.add_argument('--decoder-dir', default=package_path + "/saved_models/trajectory_vae/", help='directory from where to load the trained model of the action decoder')
parser.add_argument('--decoder-sd', default=False, help='file from where to load the trained model of the action decoder')
parser.add_argument('--encoder-dir', default=package_path + "/saved_models/state_vae/", help='directory from where to load the trained model of the state encoder')
parser.add_argument('--encoder-file', default="model_state_vae.py", help='file from where to load the network shape of the state encoder')
parser.add_argument('--encoder-sd', default=False, help='file from where to load the trained model of the state encoder')
parser.add_argument('--algorithm-dir', default="learning_algorithms", help='directory from where to load the learning algorithm')
parser.add_argument('--algorithm', default="pytorch_reinforce", help='file from where to load the learning algorithm')
parser.add_argument('--scripts-dir', default=package_path + "/scripts/", help='directory from where to load the scripts')
parser.add_argument('--image-reader', default="imager", help='file from where to load the learning algorithm')
parser.add_argument('--action-script', default="writer_from_generated", help='file from where to load the learning algorithm')
parser.add_argument('--safety-check-script', default="safety_check_client", help='script for the trajectory safety check')
parser.add_argument('--trajectory-writer-script', default="writer_from_generated", help='script publishing the trajectory')

parser.add_argument('--no-plot', nargs='?', const=True, default=False, help='whether to plot data or not')
parser.add_argument('--safe-execution-time', type=int, default=9000000000, help='safe execution time in nanoseconds')
parser.add_argument('--execution-time', type=int, default=1600000000, help='execution time in nanoseconds')
parser.add_argument('--release-frame', type=int, default=95, help='release frame')

parser.add_argument('--save-dir', default=package_path + "/saved_models/policy_network/", help='directory where to save the policy model once trained')
parser.add_argument('--save-checkpoint', default=package_path + "/saved_models/policy_network/checkpoint/", help='directory where to save the policy model once trained')
parser.add_argument('--save-file', default=False, help='name of the file to save the policy model once trained')
parser.add_argument('--load-dir', default=package_path + "/saved_models/policy_network/", help='directory from where to load the trained policy model')
parser.add_argument('--load-checkpoint', default=False, help='name of the file containing the checkpoint of the trained policy model')
parser.add_argument('--load-file', default=False, help='name of the file containing the state dictionary of the trained policy model')

parser.add_argument('--trajectory-folder', default="latest", help='folder where to look for the trajectory to execute')
parser.add_argument('--trajectory-file', default="trajectories.txt", help='file describing the trajectory to follow')

args, unknown = parser.parse_known_args()
# args = parser.parse_args()

args.trajectory_folder = package_path + "/generated_trajectories/cpp/" + args.trajectory_folder + "/"
args.cuda = not args.no_cuda and torch.cuda.is_available()
# device = torch.device("cuda" if args.cuda else "cpu")
device = "cpu"

if args.save_file != False:
    save_path = args.save_dir+args.save_file
else:
    save_path = args.save_dir+datetime.now().strftime("%Y-%m-%d_%H:%M:%S")

items = []

if not args.decoder_sd:
    print ("No decoder state dictionary specified: provide the file name of the decoder trained model using the '--decoder-sd' argument")
    sys.exit(2)
else:
    decoder_sd = torch.load(args.decoder_dir+args.decoder_sd)
    args.action_dim = len(decoder_sd["fc21.bias"])
    decoder_module = importlib.import_module(args.models_dir + "." + args.decoder_model_file)
    decoder_model = decoder_module.VAE(args.action_dim).to(device)
    decoder_model.load_state_dict(decoder_sd)
    decoder_model.eval()

if not args.algorithm:
    print ("No learning algorithm specified: provide the file name of the learning algorithm using the '--algorithm' argument")
    sys.exit(2)
else:
    algorithm_module = importlib.import_module(args.algorithm_dir + "." + args.algorithm)

action_script = importlib.import_module(args.action_script)
image_reader_module = importlib.import_module(args.image_reader)
safety_check_module = importlib.import_module(args.safety_check_script)
trajectory_writer_module = importlib.import_module(args.trajectory_writer_script)

joint_names = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7"
]
joints_number = len(joint_names)

def get_dummy_state(dim):
    # return torch.randn(dim)
    return torch.ones(dim)
    # return torch.zeros(dim)

def get_dummy_action(dim):
    # return torch.tensor([-1.0398e+00,  1.2563e+00,  8.3643e-02, -5.1169e-01,  1.4186e-01])
    return torch.zeros(dim)
    # return torch.randn(dim)
    # return torch.ones(dim)

def execute_action(input_folder, tot_time_nsecs, is_simulation, is_learning, t):
    trajectory_writer_module.talker(input_folder, tot_time_nsecs, is_simulation, is_learning, t)

def close_all(items):
    for item in items:
        item.close()

test = [
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40724661724585409,
			0.93545642930655959,
			-0.41933662556074763,
			-1.4320075802101837,
			0.44370802224428785,
			2.2730851050738083,
			-1.7492661652753791
		],
		[
			-0.40686069447372186,
			0.93503167806532927,
			-0.41935358529341654,
			-1.4328268111078344,
			0.44372688543624811,
			2.2734571413106877,
			-1.749170959547341
		],
		[
			-0.40608924687339976,
			0.93418337240293736,
			-0.41938741760523135,
			-1.4344627785476818,
			0.44376446326042446,
			2.2742001289034817,
			-1.7489798557695679
		],
		[
			-0.40493305863438928,
			0.93291388146917054,
			-0.41943794275546026,
			-1.4369105556741588,
			0.44382046286013443,
			2.2753119914219435,
			-1.7486914157966764
		],
		[
			-0.40339315989283869,
			0.9312266155228287,
			-0.41950492075196244,
			-1.4401632556757227,
			0.44389494143925895,
			2.2767906938971234,
			-1.7483028266198442
		],
		[
			-0.4014710935840442,
			0.92912633846370429,
			-0.41958807464004227,
			-1.4442108328652283,
			0.44398661937399686,
			2.2786311796249268,
			-1.7478118618396663
		],
		[
			-0.39916868634492775,
			0.92661865203210891,
			-0.41968690581791335,
			-1.4490417039825307,
			0.4440951265011287,
			2.280829054149748,
			-1.7472146206952022
		],
		[
			-0.39648804374700342,
			0.92371021184399649,
			-0.41980089391078762,
			-1.4546420562878619,
			0.44421964993469759,
			2.2833786782970282,
			-1.7465067683611739
		],
		[
			-0.3934315260899911,
			0.92040859320190183,
			-0.41992943756774276,
			-1.4609961617541256,
			0.44435925462994985,
			2.2862736308173308,
			-1.745683309248002
		],
		[
			-0.39000170803605783,
			0.91672221451971869,
			-0.42007185792899071,
			-1.4680865343552967,
			0.44451289001368999,
			2.2895067720895068,
			-1.7447386125629567
		],
		[
			-0.38620133568171516,
			0.91266025650125338,
			-0.42022740221591798,
			-1.4758940963849652,
			0.44467939692886677,
			2.2930703113473272,
			-1.7436664392255914
		],
		[
			-0.38203328202147468,
			0.90823257906516652,
			-0.4203952473340179,
			-1.4843983498030173,
			0.4448575147056783,
			2.296955875768405,
			-1.7424599694587952
		],
		[
			-0.37750050171783106,
			0.90344963791977706,
			-0.42057450338382091,
			-1.4935775487860301,
			0.44504588818272978,
			2.3011545798372568,
			-1.7411118304120625
		],
		[
			-0.37260598602365547,
			0.89832240254227791,
			-0.42076421698418182,
			-1.5034088699551806,
			0.44524307451817186,
			2.3056570935175911,
			-1.7396141232293312
		],
		[
			-0.36735271861326901,
			0.89286227712243027,
			-0.42096337432407194,
			-1.5138685771453404,
			0.44544754965160549,
			2.3104537079301486,
			-1.737958449046181
		],
		[
			-0.36174363297451501,
			0.88708102580584869,
			-0.42117090387246342,
			-1.5249321780303571,
			0.44565771430132262,
			2.3155343974191096,
			-1.7361359334851771
		],
		[
			-0.35578157190305465,
			0.88099070333111873,
			-0.42138567869011273,
			-1.5365745704030718,
			0.44587189940672939,
			2.3208888770900415,
			-1.7341372493087612
		],
		[
			-0.34946924952814085,
			0.87460359191127313,
			-0.42160651830131707,
			-1.5487701763982566,
			0.44608837095128229,
			2.3265066551049371,
			-1.7319526369819629
		],
		[
			-0.34280921619168359,
			0.86793214497477067,
			-0.42183219009740941,
			-1.5614930634198325,
			0.44630533412588647,
			2.332377079215556,
			-1.7295719229884661
		],
		[
			-0.33580382640364381,
			0.8609889381625182,
			-0.42206141025641619,
			-1.5747170509735113,
			0.44652093681568583,
			2.3384893771981923,
			-1.7269845358304912
		],
		[
			-0.32845521000979816,
			0.85378662778191816,
			-0.42229284417464125,
			-1.5884158029996578,
			0.44673327241395849,
			2.3448326910158084,
			-1.7241795197233893
		],
		[
			-0.32076524663458256,
			0.84633791675011627,
			-0.42252510641577246,
			-1.6025629056412833,
			0.44694038198513808,
			2.3513961046742051,
			-1.7211455460686629
		],
		[
			-0.31273554340304055,
			0.83865552791817466,
			-0.42275676019144132,
			-1.6171319306651442,
			0.44714025581472139,
			2.3581686658560894,
			-1.7178709228538316
		],
		[
			-0.30436741590198835,
			0.8307521845557686,
			-0.42298631639403367,
			-1.6320964849800534,
			0.44733083439709925,
			2.3651394015106915,
			-1.714343602184321
		],
		[
			-0.29566187231088531,
			0.82264059769068842,
			-0.42321223220812532,
			-1.6474302468684237,
			0.44751000892335918,
			2.3722973276480888,
			-1.7105511862019336
		],
		[
			-0.28661960061664632,
			0.81433345993658568,
			-0.42343290933137323,
			-1.6631069896695134,
			0.44767562134018302,
			2.3796314536386896,
			-1.7064809316874849
		],
		[
			-0.27724095882250149,
			0.80584344540289876,
			-0.42364669183928688,
			-1.6791005937317545,
			0.44782546405844109,
			2.3871307813518867,
			-1.7021197536829591
		],
		[
			-0.26752596806770551,
			0.79718321525953051,
			-0.423851863731248,
			-1.6953850474933907,
			0.44795727939635177,
			2.3947842994864819,
			-1.6974542285023737
		],
		[
			-0.257474308590941,
			0.78836542852204994,
			-0.42404664619772825,
			-1.7119344385623216,
			0.44806875884748681,
			2.4025809734519852,
			-1.69247059653169
		],
		[
			-0.24708531849441112,
			0.77940275762779976,
			-0.42422919465105646,
			-1.7287229356538494,
			0.4481575422688408,
			2.4105097311570587,
			-1.6871547652478451
		],
		[
			-0.23635799529650456,
			0.77030790838605312,
			-0.42439759556461326,
			-1.7457247622152148,
			0.44822121708889234,
			2.4185594450517649,
			-1.6814923129163661
		],
		[
			-0.22529100029751364,
			0.76109364390361756,
			-0.42454986316811677,
			-1.762914162523755,
			0.44825731764039117,
			2.4267189107562861,
			-1.6754684934570909
		],
		[
			-0.2138826658240863,
			0.75177281210842928,
			-0.42468393604997384,
			-1.7802653609961234,
			0.44826332472766151,
			2.4349768225924637,
			-1.669068242998998
		],
		[
			-0.202131005463071,
			0.74235837651571501,
			-0.42479767372164218,
			-1.7977525153933394,
			0.44823666554368558,
			2.443321746317622,
			-1.6622761886786015
		],
		[
			-0.19003372744327957,
			0.73286344990223995,
			-0.4248888532037946,
			-1.8153496645541702,
			0.44817471405817971,
			2.4517420893442967,
			-1.6550766602721803
		],
		[
			-0.17758825137372175,
			0.72330133057267187,
			-0.42495516569992053,
			-1.8330306712401931,
			0.44807479200431277,
			2.4602260687158859,
			-1.6474537052902531
		],
		[
			-0.1647917285982361,
			0.71368554091676084,
			-0.42499421343002736,
			-1.8507691606324521,
			0.44793417059855162,
			2.4687616770980263,
			-1.6393911082030219
		],
		[
			-0.15164106647835568,
			0.70402986796593259,
			-0.42500350670542297,
			-1.8685384549837945,
			0.44775007313519744,
			2.4773366470394707,
			-1.6308724145073934
		],
		[
			-0.13813295696769345,
			0.69434840566213907,
			-0.42498046133534895,
			-1.8863115049043395,
			0.44751967860420022,
			2.485938413755151,
			-1.6218809603886475
		],
		[
			-0.12426390989104937,
			0.68465559854978608,
			-0.42492239646754515,
			-1.9040608177414469,
			0.44724012648748412,
			2.4945540766885408,
			-1.6123999087715537
		],
		[
			-0.11003029138838329,
			0.67496628659269919,
			-0.4248265329778349,
			-1.9217583835110035,
			0.44690852289468336,
			2.5031703601206861,
			-1.6024122925947875
		],
		[
			-0.095428368026116817,
			0.66529575080211367,
			-0.42468999253851336,
			-1.9393755988446966,
			0.44652194820333491,
			2.5117735731098367,
			-1.5919010661764659
		],
		[
			-0.080454357113822095,
			0.65565975933827669,
			-0.42450979751180884,
			-1.9568831894387297,
			0.44607746637026224,
			2.5203495690684368,
			-1.5808491655644041
		],
		[
			-0.065104483790737341,
			0.64607461371743058,
			-0.42428287183285862,
			-1.9742511315236468,
			0.44557213607922647,
			2.5288837053135174,
			-1.5692395787785476
		],
		[
			-0.049375045460687828,
			0.63655719471781469,
			-0.42400604306642176,
			-1.9914485729226008,
			0.44500302388367102,
			2.5373608029620174,
			-1.5570554268503818
		],
		[
			-0.033262484152383281,
			0.62712500753319111,
			-0.42367604584268637,
			-2.0084437543264522,
			0.44436721949120456,
			2.5457651075838785,
			-1.5442800565396257
		],
		[
			-0.016763467360596186,
			0.61779622567089232,
			-0.42328952689961136,
			-2.0252039314879844,
			0.44366185331679509,
			2.5540802510724143,
			-1.5308971455560108
		],
		[
			0.00012502212209667511,
			0.60858973303448338,
			-0.42284305198162997,
			-2.0416952991232162,
			0.44288411640283198,
			2.5622892152423935,
			-1.516890821026506
		],
		[
			0.017405586948600026,
			0.59952516357010199,
			-0.42233311486639646,
			-2.057882917403715,
			0.44203128276440284,
			2.5703742977203063,
			-1.5022457918182706
		],
		[
			0.035080306211125206,
			0.59062293779229624,
			-0.42175614881125439,
			-2.073730642027602,
			0.44110073416562379,
			2.5783170807466784,
			-1.4869474951468844
		],
		[
			0.053150616511014333,
			0.58190429544210631,
			-0.4211085407276291,
			-2.0892010589652563,
			0.44008998726595605,
			2.5860984035647663,
			-1.4709822576596614
		],
		[
			0.071617183125046183,
			0.57339132347033661,
			-0.42038664840237577,
			-2.1042554250842054,
			0.43899672299282716,
			2.59369833912077,
			-1.4543374708771508
		],
		[
			0.090479761533135084,
			0.56510697848624702,
			-0.41958682108749579,
			-2.1188536159606404,
			0.43781881789777921,
			2.6010961758443298,
			-1.4370017804952095
		],
		[
			0.10973704986924251,
			0.55707510277096439,
			-0.41870542377013292,
			-2.1329540822752802,
			0.43655437713786566,
			2.6082704053103938,
			-1.4189652885899366
		],
		[
			0.12938653320780799,
			0.5493204329312078,
			-0.41773886540932603,
			-2.1465138162601827,
			0.4352017685933664,
			2.6151987165997146,
			-1.4002197672257384
		],
		[
			0.14942432100044145,
			0.54186860026878947,
			-0.41668363137991055,
			-2.1594883297003169,
			0.43375965748995188,
			2.6218579981698187,
			-1.3807588813442118
		],
		[
			0.16984497942682691,
			0.53474612197180305,
			-0.41553632029213489,
			-2.1718316449872832,
			0.4322270407428872,
			2.6282243480151313,
			-1.3605784181149061
		],
		[
			0.19064136091012168,
			0.52798038230207678,
			-0.41429368525259092,
			-2.1834963006592032,
			0.4306032800897725,
			2.6342730928277351,
			-1.3396765191715883
		],
		[
			0.21180443355590842,
			0.5215996030681892,
			-0.41295267949295106,
			-2.1944333727262522,
			0.42888813293595657,
			2.6399788167623504,
			-1.3180539113603089
		],
		[
			0.23332311378455295,
			0.51563280284178281,
			-0.41151050611362305,
			-2.2045925128607506,
			0.4270817797148474,
			2.6453154002543542,
			-1.2957141308181475
		],
		[
			0.25518410591344826,
			0.51010974460420966,
			-0.40996467146742754,
			-2.2139220042098073,
			0.42518484647753152,
			2.6502560691323849,
			-1.2726637344230132
		],
		[
			0.27737175287651777,
			0.50506087180626735,
			-0.40831304144439112,
			-2.2223688351542927,
			0.4231984213871699,
			2.6547734540030987,
			-1.2489124919532177
		],
		[
			0.29986790260746871,
			0.50051723318956343,
			-0.40655389961737792,
			-2.2298787907801905,
			0.4211240638183027,
			2.6588396595625849,
			-1.2244735517263055
		],
		[
			0.32265179482203332,
			0.49651039715468182,
			-0.40468600587948977,
			-2.2363965611408125,
			0.41896380486239732,
			2.6624263431069695,
			-1.1993635721103637
		],
		[
			0.34569997297414123,
			0.49307235696584883,
			-0.40270865386424054,
			-2.2418658645704399,
			0.41672013822772508,
			2.6655048010771187,
			-1.1736028111794568
		],
		[
			0.36898622599617525,
			0.49023542864722591,
			-0.40062172511151828,
			-2.2462295833673616,
			0.41439600079682209,
			2.668046061985788,
			-1.1472151669754249
		],
		[
			0.39248156403550216,
			0.4880321440409488,
			-0.39842573765578132,
			-2.24942990811053,
			0.41199474246315021,
			2.6700209835504225,
			-1.120228161388376
		],
		[
			0.41615423175047001,
			0.48649514214582751,
			-0.39612188650253144,
			-2.2514084857298764,
			0.40952008529500272,
			2.6714003513046665,
			-1.0926728616077017
		],
		[
			0.43996976182500097,
			0.48565706251935664,
			-0.39371207336178587,
			-2.2521065652431527,
			0.40697607254420282,
			2.6721549754027194,
			-1.0645837344309592
		],
		[
			0.46389107021442966,
			0.48555044518335538,
			-0.39119892305833925,
			-2.2514651338340652,
			0.40436700849548524,
			2.6722557817803119,
			-1.0359984304267491
		],
		[
			0.4878785932762984,
			0.48620764210474215,
			-0.38858578426638679,
			-2.2494250347102041,
			0.40169739059916987,
			2.6716738933109228,
			-1.0069574969750652
		],
		[
			0.51189046541522532,
			0.48766074591056413,
			-0.38587671263634837,
			-2.2459270569740273,
			0.39897183570217348,
			2.6703806961092957,
			-0.97750402146696469
		],
		[
			0.53588273424122956,
			0.4899415420305786,
			-0.38307643499238742,
			-2.2409119865844769,
			0.39619500245126354,
			2.6683478856934406,
			-0.9476832083179848
		],
		[
			0.560145881506244,
			0.49238217574137966,
			-0.38063920269529511,
			-2.2345052169388619,
			0.39289219330305164,
			2.6650440249221057,
			-0.9172075862170912
		],
		[
			0.58548118969463003,
			0.49300934515668104,
			-0.3798063396444249,
			-2.227189906838984,
			0.38774466412646624,
			2.6590134840756434,
			-0.88528742241847125
		],
		[
			0.61073332490853294,
			0.49324141398947374,
			-0.37958043198555391,
			-2.218658659663344,
			0.38182396404463559,
			2.6513535841872571,
			-0.85310542038507065
		],
		[
			0.63530439828491347,
			0.49436055493793146,
			-0.379113297380963,
			-2.2085578059047588,
			0.37600175397284286,
			2.6429814097596429,
			-0.82122510703473051
		],
		[
			0.65916301958471679,
			0.49637465272087833,
			-0.37840201066929929,
			-2.1968890584925855,
			0.37030679337108102,
			2.6339070408507781,
			-0.78970043928032552
		],
		[
			0.68228295124652549,
			0.4992907993700888,
			-0.37744727866041933,
			-2.1836541426856457,
			0.36476403829268023,
			2.6241401140909733,
			-0.75857913174438063
		],
		[
			0.70464287798334047,
			0.50311540267561472,
			-0.37625315415928201,
			-2.1688543974792314,
			0.35939443058692616,
			2.6136895759812657,
			-0.72790239404202817
		]
	]

test2 = []
for point in test:
    test2.extend(point)

mc_latent_space_means = [-0.95741573,  0.60835766,  0.03808778, -0.70411791,  0.15081754]
mc_latent_space_stds = [0.14915584, 0.77813671, 0.15265675, 0.17448557, 0.12238263]
mc_best_mean = [-0.9914,  0.7875,  0.0775, -0.6818,  0.1817]
mc_best_std = [0.0538, 0.0181, 0.3415, 0.0175, 0.2323]
mc_best_mean_faster = [-1.0914,  1.0875,  0.0775, -0.5818,  0.1817]
mc_fastest = [-1.2, 1.9, 0.3, -0.4, 0.4]

test_action = [-0.79844596, -0.63713676, -0.12888897, -0.97707188,  0.01480127]

mc_13_means = [-0.79844596, -0.23713676, -0.12888897, -0.87707188,  0.01480127]
mc_14_means = [-0.8877851 ,  0.24533824, -0.02885615, -0.79018154,  0.09704519]
mc_15_means = [-0.97981189,  0.71057909,  0.05748677, -0.69583368,  0.17542016]
mc_16_means = [-1.0606842 ,  1.14844979,  0.14893559, -0.59407567,  0.23862324]
mc_17_means = [-1.13784433,  1.55074548,  0.22355699, -0.49421183,  0.28466991]
mc_18_means = [-1.1728737 ,  1.76443983,  0.26582965, -0.45975538,  0.30441109]

initial_means = [mc_13_means] + [mc_14_means] + [mc_15_means] + [mc_16_means] + [mc_17_means] + [mc_18_means]
reversed_initial_means = [mc_18_means] + [mc_17_means] + [mc_16_means] + [mc_15_means] + [mc_14_means] + [mc_13_means]
shuffled_initial_means = [mc_18_means] + [mc_15_means] + [mc_13_means] + [mc_17_means] + [mc_14_means] + [mc_16_means]

mc_latent_space_means_b0 = [-2.3453495 ,  1.87199709,  0.66421834, -2.87626281,  1.57093551]
mc_latent_space_stds_b0 = [0.41007773, 1.01831094, 0.45268615, 0.01925819, 0.65967075]
mc_best_mean_b0 = [-1.5954519510269165, -0.0013902420178055763, -0.16062034666538239, -2.9057390689849854, 0.356065958738327]
mc_best_std_b0 = [0.008678837679326534, 0.016342472285032272, 0.016840659081935883, 0.004060306120663881, 0.00893393438309431]

ll_latent_space_means = [-1.54930503,  0.25162958,  0.05412535, -1.4289467 , -0.06778317]
ll_latent_space_stds = [0.42513496, 0.01628749, 0.06014936, 0.02778022, 0.51911289]
ll_best_mean = [-1.3671,  0.2444,  0.0290, -1.4391,  0.1555]
ll_best_std = [0.0204, 0.2391, 0.2653, 0.0247, 0.0492]

def get_angle(x, y):
    return (math.atan2(y, x)*180/math.pi + 360) % 360

def main(args):
    try:
        plot_joints = False
        image_reader = image_reader_module.image_converter()
        items.append(image_reader)
        image_reader.initialize_board()
        algorithm = algorithm_module.ALGORITHM(args.state_dim, args.action_dim, args.learning_rate, plot=True, batch_size=args.batch_size)
        items.append(algorithm)
        if args.load_file != False:
            algorithm.load_model_state_dict(args.load_dir+args.load_file)
        elif args.load_checkpoint != False:
            algorithm.load_checkpoint(args.load_dir+"checkpoint/"+args.load_checkpoint)
        else:
            algorithm.plot = False
            algorithm.pre_train(args.pre_train_epochs, args.pre_train_batch_size, args.pre_train_log_interval, target=torch.tensor(mc_latent_space_means))
            print ("Pre train over")
            algorithm.plot = True
        ret = [0, 0]
        reward = None
        trajectory_dict = {
            "joint_trajectory": [],
            "joint_names": joint_names,
            "realease_frame": args.release_frame
        }
        safe_throws = 0
        epoch = 0
        while safe_throws < args.safe_throws:
        # for epoch in range(args.epochs):
            # t = 0
            # while t < args.batch_size:
            for t in range(args.batch_size):
                print ("t = {}".format(t))
                state = get_dummy_state(algorithm.policy.in_dim)
                command = raw_input("Enter command (leave blank to execute action): ")
                if "" != command:
                    if "set_action" == command:
                        while True:
                            try:
                                a = raw_input("Input the action in the form of a list ('q' to quit): ")
                                if "q" == a:
                                    break
                                action = torch.tensor(ast.literal_eval(a))
                                mean = torch.tensor(ast.literal_eval(a))
                                break
                            except:
                                print ("The action must be a python list\nEg: [1, 2, 3, 4, 5]")
                if "set_action" != command:
                    if epoch == 0:
                        action, mean = algorithm.select_action(state, target_action=torch.tensor(shuffled_initial_means[t]))
                    else:
                        action, mean = algorithm.select_action(state)
                # action, mean = algorithm.select_action(state, cov_mat=cov_mat)
                if epoch % args.log_interval == 0 and t == 0 and algorithm.plot:
                    algorithm.update_graphs()
                # action = get_dummy_action(algorithm.policy.out_dim)
                trajectory = decoder_model.decode(action)

                # trajectory = decoder_model.decode(torch.tensor(mc_13_means))

                smooth_trajectory = []
                for i in range(joints_number):
                    smooth_trajectory.append(trajectory[i])
                for i, point in enumerate(trajectory[joints_number:], joints_number):
                    smooth_trajectory.append(0.6*smooth_trajectory[i-joints_number]+0.4*point)
                smooth_trajectory = torch.tensor(smooth_trajectory)

                is_safe, avg_distance, unsafe_pts, fk_z = safety_check_module.check(smooth_trajectory.tolist())
                # is_safe, avg_distance, unsafe_pts, fk_z = safety_check_module.check(trajectory.tolist())
                
                if is_safe:
                    print("Distribution mean:")
                    print(mean)
                    print("Action to execute:")
                    print(action)
                    ret[0] += 1
                    trajectory_dict["joint_trajectory"] = smooth_trajectory.view(100, -1).tolist()
                    if plot_joints:
                        plotter_module.plot_joints(trajectory_dict["joint_trajectory"])
                    
                    cumulative_reward = 0
                    for n in range(args.action_repetition):
                        safe_throws += 1
                        print("\nn = {}".format(n+1))
                        # execute_action(input_folder=False, tot_time_nsecs=args.safe_execution_time, is_simulation=False, is_learning=True, t=trajectory_dict)
                        execute_action(input_folder=False, tot_time_nsecs=args.execution_time, is_simulation=False, is_learning=True, t=trajectory_dict)
                        command = raw_input("Press enter to evaluate the board\n")
                        if "print rewards_history" == command:
                            print ("rewards_history:")
                            print (algorithm.policy.rewards_history)

                        while True:
                            distance, stone_x, stone_y = image_reader.evaluate_board()
                            if distance != -1:
                                reward = max(0, 4 - distance//100)
                                angle = get_angle(stone_x, stone_y)
                                # if distance > 350:
                                #     reward = 0
                                # else:
                                #     reward = (1-(distance/350.0))**2
                                break
                            else:
                                command = raw_input("'c'=continue\n's'=set reward\n't'=try again\n'o'=out of bounds\n\nInput command: ")
                                if "c" == command:
                                    break
                                elif "s" == command:
                                    while True:
                                        try:
                                            r = raw_input("Set the reward: ")
                                            if "q" != r:
                                                reward = float(r)
                                                distance = "set"
                                                angle = "set"
                                            break
                                        except:
                                            print("INFO: Input 't' to try again evaluating the board")
                                            print("ERROR: The reward must be a float")
                                    break
                                elif "o" == command:
                                    reward = 0
                                    distance = "out"
                                    angle = "out"
                                    break
                                elif "t" == command:
                                    pass
                        cumulative_reward += reward
                        algorithm.set_stone_position(distance, angle)
                        print ("distance = {}".format(distance))
                        print ("reward = {}".format(reward))
                        print ("cumulative_reward = {}".format(cumulative_reward))
                    reward = float(cumulative_reward)/args.action_repetition
                else:
                    ret[1] += 1
                    reward = -unsafe_pts
                    algorithm.set_stone_position("unsafe", "unsafe")
                print (ret)
                print ("unsafe_pts = " + str(unsafe_pts))

                print ("reward = {}".format(reward))      
                algorithm.set_reward(reward)
            loss = algorithm.finish_episode()

            print("Saving policy model...")
            algorithm.save_model_state_dict(save_path)
            checkpoint_save_path = args.save_dir+"checkpoint/"+datetime.now().strftime("%Y-%m-%d_%H:%M:%S")+".tar"
            algorithm.save_checkpoint(checkpoint_save_path)
            print("Policy model saved...")

            if epoch % args.log_interval == 0:
                print('Episode {}\tLast reward: {:.2f}'.format(
                    epoch, reward))
            epoch += 1

        raw_input("Execution finished, press enter to close the program.")
        close_all(items)

    except KeyboardInterrupt:
        print("Shutting down")
        close_all(items)


if __name__ == '__main__':
    main(args)