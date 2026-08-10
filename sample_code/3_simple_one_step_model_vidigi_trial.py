"""
This is the one-step model from the second simpy session (2B)
"""

import simpy
from sim_tools.distributions import Exponential, Lognormal
import pandas as pd
from vidigi.logging import EventLogger
from vidigi.utils import create_event_position_df, EventPosition
from vidigi.animation import animate_activity_log
from vidigi.resources import VidigiStore  # NEW


class Patient:
    def __init__(self, p_id):
        self.id = p_id
        self.q_time_nurse = pd.NA


class Param:
    def __init__(
        self,
        mean_patient_inter=5,
        mean_nurse_consult_time=6,
        sd_nurse_consult_time=1,
        num_nurses=1,
        sim_duration=120,
        num_replications=5,
    ):
        self.mean_patient_inter = mean_patient_inter
        self.mean_nurse_consult_time = mean_nurse_consult_time
        self.sd_nurse_consult_time = sd_nurse_consult_time
        self.num_nurses = num_nurses
        self.sim_duration = sim_duration
        self.num_replications = num_replications


class Model:
    def __init__(self, param):
        self.param = param
        self.env = simpy.Environment()
        self.patient_counter = 0
        self.nurse = VidigiStore(self.env, num_resources=self.param.num_nurses)
        self.patient_inter_dist = Exponential(mean=self.param.mean_patient_inter)
        self.nurse_consult_time_dist = Lognormal(
            mean=self.param.mean_nurse_consult_time,
            stdev=self.param.sd_nurse_consult_time,
        )
        self.list_of_patients = []
        self.mean_q_time_nurse = pd.NA
        self.sd_q_time_nurse = pd.NA
        self.perc_90_q_time_nurse = pd.NA

        self.logger = EventLogger(env=self.env, run_number=1)

    def generator_patient_arrivals(self):
        while True:
            self.patient_counter += 1
            p = Patient(self.patient_counter)
            self.list_of_patients.append(p)
            self.env.process(self.attend_clinic(p))
            sampled_inter = self.patient_inter_dist.sample()
            yield self.env.timeout(sampled_inter)

    def attend_clinic(self, patient):
        self.logger.log_arrival(entity_id=patient.id)

        start_q_nurse = self.env.now

        self.logger.log_queue(entity_id=patient.id, event="nurse_wait_begins")

        with self.nurse.request() as req:
            nurse_obtained = yield req

            end_q_nurse = self.env.now
            patient.q_time_nurse = end_q_nurse - start_q_nurse

            self.logger.log_resource_use_start(
                entity_id=patient.id,
                event="being_seen_by_nurse",
                resource_id=nurse_obtained.id_attribute,
            )

            sampled_nurse_act_time = self.nurse_consult_time_dist.sample()
            yield self.env.timeout(sampled_nurse_act_time)

            self.logger.log_resource_use_end(
                entity_id=patient.id,
                event="nurse_treatment_ends",
                resource_id=nurse_obtained.id_attribute,
            )

        self.logger.log_departure(entity_id=patient.id)

    def run_model(self):
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=self.param.sim_duration)

    def convert_entity_list_to_dataframe(self, entity_list):
        entity_dateframe = pd.DataFrame(entity.__dict__ for entity in entity_list)
        return entity_dateframe

    def calculate_run_results(self, entity_dataframe):
        self.mean_q_time_nurse = entity_dataframe["q_time_nurse"].mean()
        self.sd_q_time_nurse = entity_dataframe["q_time_nurse"].std()
        self.perc_90_q_time_nurse = entity_dataframe["q_time_nurse"].quantile(0.9)

    def get_vidigi_event_log(self):
        return self.logger.to_dataframe()


# NEW - but you've seen all this before.
# It's *almost* identical to the content in session 2C!
# We don't need to make any changes to it for the purposes
# of getting the animation working - our changes will just
# be in how we pass the event log to the animation
# so we will make a little helper method at the end of this
# class for that purpose
class Trial:
    def __init__(self, param):
        self.param = param
        self.list_of_simulation_replications = []
        self.trial_mean_q_time_nurse = pd.NA
        self.trial_sd_q_time_nurse = pd.NA
        self.trial_perc_90_q_time_nurse = pd.NA

    def run_trial(self):
        for replication_id in range(self.param.num_replications):
            model_replication = Model(self.param)
            model_replication.run_model()
            patient_df = model_replication.convert_entity_list_to_dataframe(
                model_replication.list_of_patients
            )
            model_replication.calculate_run_results(patient_df)
            self.list_of_simulation_replications.append(model_replication)

    def calculate_trial_results(self):
        self.replication_df = pd.DataFrame(
            replication.__dict__ for replication in self.list_of_simulation_replications
        )

        self.trial_mean_q_time_nurse = self.replication_df["mean_q_time_nurse"].mean()

        self.trial_sd_q_time_nurse = self.replication_df["mean_q_time_nurse"].std()

        self.trial_perc_90_q_time_nurse = self.replication_df[
            "mean_q_time_nurse"
        ].quantile(0.9)

    # NEW
    # This bit really is new!
    # We're going to make a small helper function to pull back the run
    # we are interested in
    # Remember - Python counts from 0
    def get_run(self, run=0):
        return self.list_of_simulation_replications[run]


class Animation:
    def __init__(self, params, event_log):
        self.params = params
        self.event_log = event_log

        self.layout = create_event_position_df(
            [
                EventPosition(event="arrival", x=0, y=350, label="Entrance"),
                EventPosition(
                    event="nurse_wait_begins", x=200, y=250, label="Waiting for Nurse"
                ),
                EventPosition(
                    event="being_seen_by_nurse",
                    x=200,
                    y=150,
                    label="Being Seen By Nurse",
                    resource="num_nurses",
                ),
                EventPosition(event="depart", x=200, y=50, label="Exit"),
            ]
        )

    def generate_animation(self, time_interval=1):
        return animate_activity_log(
            event_log=self.event_log,
            event_position_df=self.layout,
            every_x_time_units=time_interval,
            scenario=self.params,
        )


# NEW (but again, you've seen this before in session 2C)
# Rather than an individual run, we're just
my_params = Param(mean_patient_inter=3, num_nurses=2, mean_nurse_consult_time=10)
my_trial = Trial(my_params)
my_trial.run_trial()
my_trial.calculate_trial_results()
print("TRIAL RESULTS")
print("-----------------------")
print("Queuing Time for the Nurse")
print(f"Mean : {my_trial.trial_mean_q_time_nurse:.2f} minutes")
print(f"SD : {my_trial.trial_sd_q_time_nurse:.2f} minutes")
print(f"90th Perc : {my_trial.trial_perc_90_q_time_nurse:.2f} minutes")
print()

# NEW
# Now instead of just calling 'get_vidigi_event_log()' directly
# on our model run, we just grab back our chosen run from the trial
# first (remembering that Python counts from 0)
# Because that's the *entire* model object, we still have access to
# any of the methods or attributes of that model object, so we can now
# grab back
my_event_log = my_trial.get_run(run=2).get_vidigi_event_log()
print(my_event_log.head(10))

my_animation = Animation(my_params, my_event_log)
my_animation.generate_animation()
